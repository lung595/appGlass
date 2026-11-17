// appglass-ck.so: "colour-key glass" for EGL/OpenGL apps that paint opaque pixels.
// LD_PRELOAD shim that runs one full-screen shader pass on the window back buffer
// right before eglSwapBuffers*. Pixels close to a key colour (the app's own
// background colours) get that key's alpha; anti-aliased text edges are un-mixed
// with GIMP's "colour to alpha" formula, so glyph cores stay alpha 1.0 and the
// edge keeps the correct premultiplied colour:
//     a_t   = colour-to-alpha opacity of P against key K   (0 = pure key, 1 = unrelated colour)
//     out.a = 1 - (1 - a_t) * (1 - A)
//     out.rgb (premultiplied) = P - (1 - a_t) * (1 - A) * K
// Pixels that are already translucent (CSD shadow, earlier passes) are left alone,
// so the pass is idempotent when the app redraws only part of a reused (buffer-age) buffer.
//
//   LD_PRELOAD=/path/appglass-ck.so APPGLASS_KEYS="f4fbf8:0.60,e6ede9:0.65" [APPGLASS_TOL=0.02] [APPGLASS_SNAP=0.75] [APPGLASS_DEBUG=1] app
//   [APPGLASS_MAXFPS=60]   cap swaps per second (software GL on a 240 Hz output otherwise renders and keys every
//                          animation frame on the CPU: 4x the work for no visible gain). 0 or unset = no cap.
//                          The cap is per process: all windows and render threads share it.
//   [APPGLASS_TRACE=file]  append (O_CLOEXEC) one line per swap: CLOCK_MONOTONIC ms, gap to the previous swap, pass ms.
//                          Gaps that sit on ~1000 ms during an animation mean the compositor is only sending
//                          throttled frame callbacks (it treats the window as not visible).
//
//   [APPGLASS_SCRUB="VAR VAR"] children started with exec*/fexecve/posix_spawn*/pidfd_spawn*/system/popen lose
//                          the shim, APPGLASS_* and VAR.
//
// The EGL surface must have an alpha channel (check the wl_buffer format: AR24
// works, XR24 does not). Hooks are reached through the PLT, through dlsym()
// (libepoxy resolves eglSwapBuffers with dlsym on its own libEGL handle) and
// through eglGetProcAddress (the *WithDamage* extensions).
//
// While keys are set, the app's wl_surface.set_opaque_region requests are sent with a NULL
// (empty) region. An app that thinks it is opaque (winit with transparent: false marks the
// whole surface opaque) would otherwise tell the compositor that the keyed, translucent pixels
// are opaque. Measured with winit's full-surface region: the window is glass when the app commits,
// but when niri redraws it without a commit it leaves out the blur and backdrop and the whole window
// turns dark (alpha ~210). A blinking cursor plus such a redraw flashes the window once a second.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <EGL/egl.h>

static int dbg(void) { static int d = -1; if (d < 0) d = getenv("APPGLASS_DEBUG") != NULL; return d; }
#define LOG(...) do { if (dbg()) { fprintf(stderr, "[appglass-ck] " __VA_ARGS__); fputc('\n', stderr); } } while (0)

typedef void *(*dlsym_fn)(void *, const char *);
static dlsym_fn real_dlsym_p;
static void *real_dlsym(void *h, const char *n) {
    if (!real_dlsym_p) {
        real_dlsym_p = (dlsym_fn)dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.34");
        if (!real_dlsym_p) real_dlsym_p = (dlsym_fn)dlvsym(RTLD_NEXT, "dlsym", "GLIBC_2.2.5");
    }
    return real_dlsym_p(h, n);
}

typedef EGLBoolean (*swap_fn)(EGLDisplay, EGLSurface);
typedef EGLBoolean (*swapd_fn)(EGLDisplay, EGLSurface, const EGLint *, EGLint);
typedef void *(*gpa_fn)(const char *);
static swap_fn r_swap; static swapd_fn r_swap_ext, r_swap_khr; static gpa_fn r_gpa;

static void *egl_lib(void) {
    static void *h; if (!h) h = dlopen("libEGL.so.1", RTLD_LAZY | RTLD_NOLOAD); if (!h) h = dlopen("libEGL.so.1", RTLD_LAZY);
    return h;
}
static void resolve(void) {
    if (!r_gpa) r_gpa = (gpa_fn)real_dlsym(egl_lib(), "eglGetProcAddress");
    if (!r_swap) r_swap = (swap_fn)real_dlsym(egl_lib(), "eglSwapBuffers");
}

/* ---------------- GL pass ---------------- */
typedef unsigned int GLenum, GLuint; typedef int GLint, GLsizei; typedef unsigned char GLboolean; typedef float GLfloat; typedef char GLchar;
#define GL_TEXTURE_2D 0x0DE1
#define GL_TEXTURE0 0x84C0
#define GL_RGBA 0x1908
#define GL_RGBA8 0x8058
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_NEAREST 0x2600
#define GL_TRIANGLES 0x0004
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_VERTEX_SHADER 0x8B31
#define GL_COMPILE_STATUS 0x8B81
#define GL_LINK_STATUS 0x8B82
#define GL_CURRENT_PROGRAM 0x8B8D
#define GL_ACTIVE_TEXTURE 0x84E0
#define GL_TEXTURE_BINDING_2D 0x8069
#define GL_VERTEX_ARRAY_BINDING 0x85B5
#define GL_DRAW_FRAMEBUFFER_BINDING 0x8CA6
#define GL_READ_FRAMEBUFFER_BINDING 0x8CAA
#define GL_DRAW_FRAMEBUFFER 0x8CA9
#define GL_READ_FRAMEBUFFER 0x8CA8
#define GL_VIEWPORT 0x0BA2
#define GL_SCISSOR_TEST 0x0C11
#define GL_BLEND 0x0BE2
#define GL_DEPTH_TEST 0x0B71
#define GL_STENCIL_TEST 0x0B90
#define GL_CULL_FACE 0x0B44
#define GL_FRAMEBUFFER_SRGB 0x8DB9
#define GL_COLOR_WRITEMASK 0x0C23
#define GL_READ_BUFFER 0x0C02
#define GL_DRAW_BUFFER 0x0C01
#define GL_BACK 0x0405
#define GL_VERSION 0x1F02
#define GL_SAMPLER_BINDING 0x8919
#define GL_UNPACK_ALIGNMENT 0x0CF5

static struct {
    void (*GetIntegerv)(GLenum, GLint *); GLboolean (*IsEnabled)(GLenum); void (*Enable)(GLenum); void (*Disable)(GLenum);
    const unsigned char *(*GetString)(GLenum);
    void (*GenTextures)(GLsizei, GLuint *); void (*BindTexture)(GLenum, GLuint); void (*ActiveTexture)(GLenum);
    void (*TexParameteri)(GLenum, GLenum, GLint); void (*CopyTexImage2D)(GLenum, GLint, GLenum, GLint, GLint, GLsizei, GLsizei, GLint);
    GLuint (*CreateShader)(GLenum); void (*ShaderSource)(GLuint, GLsizei, const GLchar *const *, const GLint *);
    void (*CompileShader)(GLuint); void (*GetShaderiv)(GLuint, GLenum, GLint *); void (*GetShaderInfoLog)(GLuint, GLsizei, GLsizei *, GLchar *);
    GLuint (*CreateProgram)(void); void (*AttachShader)(GLuint, GLuint); void (*LinkProgram)(GLuint); void (*GetProgramiv)(GLuint, GLenum, GLint *);
    void (*UseProgram)(GLuint); GLint (*GetUniformLocation)(GLuint, const GLchar *);
    void (*Uniform1i)(GLint, GLint); void (*Uniform1f)(GLint, GLfloat); void (*Uniform3fv)(GLint, GLsizei, const GLfloat *); void (*Uniform1fv)(GLint, GLsizei, const GLfloat *);
    void (*GenVertexArrays)(GLsizei, GLuint *); void (*BindVertexArray)(GLuint); void (*BindFramebuffer)(GLenum, GLuint);
    void (*Viewport)(GLint, GLint, GLsizei, GLsizei); void (*ColorMask)(GLboolean, GLboolean, GLboolean, GLboolean); void (*GetBooleanv)(GLenum, GLboolean *);
    void (*DrawArrays)(GLenum, GLint, GLsizei); void (*ReadBuffer)(GLenum); void (*BindSampler)(GLuint, GLuint);
} gl;

#define MAXK 8
static float keys[MAXK * 3], alphas[MAXK]; static int nkeys; static float tol = 0.02f, snap = 0.75f;
/* runs once per process (pthread_once): the render thread and the Wayland thread may both ask first */
static void parse_keys(void) {
    const char *s = getenv("APPGLASS_KEYS"); if (!s) return;
    const char *e = getenv("APPGLASS_TOL"); if (e) tol = strtof(e, NULL);
    e = getenv("APPGLASS_SNAP"); if (e) snap = strtof(e, NULL);  /* colour-to-alpha opacity >= snap -> fully opaque (glyph cores) */
    while (*s && nkeys < MAXK) {
        unsigned rgb; float a; int n = 0;
        if (sscanf(s, "%6x:%f%n", &rgb, &a, &n) != 2) break;
        keys[nkeys * 3] = ((rgb >> 16) & 255) / 255.f; keys[nkeys * 3 + 1] = ((rgb >> 8) & 255) / 255.f; keys[nkeys * 3 + 2] = (rgb & 255) / 255.f;
        alphas[nkeys++] = a; s += n; while (*s == ',' || *s == ' ') s++;
    }
    LOG("%d keys, tol %.3f snap %.2f", nkeys, tol, snap);
}
static pthread_once_t keys_once = PTHREAD_ONCE_INIT;
static int nkeys_get(void) { pthread_once(&keys_once, parse_keys); return nkeys; }

static const char *FS_BODY =
    "uniform sampler2D t; uniform vec3 K[8]; uniform float A[8]; uniform int N; uniform float tol; uniform float snap;\n"
    "float c2a(vec3 p, vec3 k){ vec3 d = vec3(0.0);\n"
    "  for (int i=0;i<3;i++){ float pi=p[i], ki=k[i];\n"
    "    if (pi>ki) d[i]=(pi-ki)/max(1.0-ki,1e-4); else if (pi<ki) d[i]=(ki-pi)/max(ki,1e-4); }\n"
    "  return max(d.r,max(d.g,d.b)); }\n"
    "void main(){ vec4 p = texelFetch(t, ivec2(gl_FragCoord.xy), 0);\n"
    "  if (p.a < 0.999 || N == 0) { O = p; return; }\n"
    "  float best = 1.0; int bi = 0;\n"
    "  for (int i=0;i<8;i++){ if (i>=N) break; float a = c2a(p.rgb, K[i]); if (a < best){ best = a; bi = i; } }\n"
    "  float at = clamp((best - tol) / (1.0 - tol), 0.0, 1.0); at = at >= snap ? 1.0 : at / snap;\n"
    "  if (at >= 1.0) { O = p; return; }\n"
    "  vec3 k = K[0]; float aa = A[0]; for (int i=0;i<8;i++){ if (i==bi){ k=K[i]; aa=A[i]; } }\n"
    "  float m = (1.0 - at) * (1.0 - aa);\n"
    "  O = vec4(max(p.rgb - m * k, 0.0), 1.0 - m); }\n";
static const char *VS_BODY =
    "void main(){ vec2 v = vec2(float((gl_VertexID<<1)&2), float(gl_VertexID&2)); gl_Position = vec4(v*2.0-1.0, 0.0, 1.0); }\n";

typedef struct { EGLContext ctx; GLuint prog, tex, vao; int ok; int es; } ctxstate;
static ctxstate cs[8]; static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

static void *gp(const char *n) { void *p = r_gpa ? r_gpa(n) : NULL; if (!p) p = real_dlsym(RTLD_DEFAULT, n); return p; }
static int load_gl(void) {
    static int done = 0; if (done) return done > 0;
#define L(x) if (!(*(void **)&gl.x = gp("gl" #x))) { LOG("no gl" #x); done = -1; return 0; }
    L(GetIntegerv) L(IsEnabled) L(Enable) L(Disable) L(GetString) L(GenTextures) L(BindTexture) L(ActiveTexture) L(TexParameteri)
    L(CopyTexImage2D) L(CreateShader) L(ShaderSource) L(CompileShader) L(GetShaderiv) L(GetShaderInfoLog) L(CreateProgram)
    L(AttachShader) L(LinkProgram) L(GetProgramiv) L(UseProgram) L(GetUniformLocation) L(Uniform1i) L(Uniform1f) L(Uniform3fv)
    L(Uniform1fv) L(GenVertexArrays) L(BindVertexArray) L(BindFramebuffer) L(Viewport) L(ColorMask) L(GetBooleanv) L(DrawArrays)
#undef L
    *(void **)&gl.ReadBuffer = gp("glReadBuffer"); *(void **)&gl.BindSampler = gp("glBindSampler");
    done = 1; return 1;
}

static GLuint shader(GLenum type, const char *hdr, const char *body) {
    GLuint s = gl.CreateShader(type); const char *src[2] = { hdr, body }; gl.ShaderSource(s, 2, src, NULL); gl.CompileShader(s);
    GLint ok = 0; gl.GetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; gl.GetShaderInfoLog(s, sizeof log, NULL, log); LOG("shader error: %s", log); return 0; }
    return s;
}

static ctxstate *state_for(EGLContext c) {
    for (int i = 0; i < 8; i++) if (cs[i].ctx == c) return &cs[i];
    for (int i = 0; i < 8; i++) if (!cs[i].ctx) { cs[i].ctx = c; return &cs[i]; }
    return NULL;
}

static void pass(EGLDisplay dpy, EGLSurface surf) {
    if (!nkeys_get()) return;
    resolve();
    EGLContext (*getctx)(void) = (EGLContext (*)(void))real_dlsym(egl_lib(), "eglGetCurrentContext");
    EGLBoolean (*qs)(EGLDisplay, EGLSurface, EGLint, EGLint *) = (EGLBoolean (*)(EGLDisplay, EGLSurface, EGLint, EGLint *))real_dlsym(egl_lib(), "eglQuerySurface");
    EGLBoolean (*gca)(EGLDisplay, EGLConfig, EGLint, EGLint *) = (EGLBoolean (*)(EGLDisplay, EGLConfig, EGLint, EGLint *))real_dlsym(egl_lib(), "eglGetConfigAttrib");
    EGLBoolean (*gcf)(EGLDisplay, EGLConfig *, EGLint, EGLint *) = (EGLBoolean (*)(EGLDisplay, EGLConfig *, EGLint, EGLint *))real_dlsym(egl_lib(), "eglGetConfigs");
    EGLContext c = getctx ? getctx() : EGL_NO_CONTEXT; if (c == EGL_NO_CONTEXT || !qs) return;
    EGLint w = 0, h = 0, cfgid = 0; qs(dpy, surf, EGL_WIDTH, &w); qs(dpy, surf, EGL_HEIGHT, &h); qs(dpy, surf, EGL_CONFIG_ID, &cfgid);
    if (w <= 0 || h <= 0 || !load_gl()) return;
    pthread_mutex_lock(&mu);
    ctxstate *st = state_for(c);
    if (!st || st->ok < 0) { pthread_mutex_unlock(&mu); return; }
    if (!st->ok) {
        // alpha bits of the surface config (log only: an XRGB surface will drop the alpha we write)
        if (gca && gcf) { EGLConfig cf[512]; EGLint n = 0; gcf(dpy, cf, 512, &n);
            for (int i = 0; i < n; i++) { EGLint id; gca(dpy, cf[i], EGL_CONFIG_ID, &id); if (id == cfgid) { EGLint a = 0; gca(dpy, cf[i], EGL_ALPHA_SIZE, &a); LOG("surface %dx%d config %d alpha bits %d", w, h, cfgid, a); } } }
        const char *ver = (const char *)gl.GetString(GL_VERSION); st->es = ver && strstr(ver, "OpenGL ES");
        LOG("GL_VERSION %s", ver ? ver : "?");
        const char *vh = st->es ? "#version 300 es\n" : "#version 150\n";
        const char *fh = st->es ? "#version 300 es\nprecision highp float; precision highp int; out vec4 O;\n" : "#version 150\nout vec4 O;\n";
        GLuint vs = shader(GL_VERTEX_SHADER, vh, VS_BODY), fs = shader(GL_FRAGMENT_SHADER, fh, FS_BODY);
        if (!vs || !fs) { st->ok = -1; pthread_mutex_unlock(&mu); return; }
        st->prog = gl.CreateProgram(); gl.AttachShader(st->prog, vs); gl.AttachShader(st->prog, fs); gl.LinkProgram(st->prog);
        GLint ok = 0; gl.GetProgramiv(st->prog, GL_LINK_STATUS, &ok); if (!ok) { LOG("link failed"); st->ok = -1; pthread_mutex_unlock(&mu); return; }
        gl.GenTextures(1, &st->tex); gl.GenVertexArrays(1, &st->vao); st->ok = 1;
    }
    // save state
    GLint prog, atex, tex0, vao, dfb, rfb, vp[4], rbuf = 0, smp = 0; GLboolean cm[4];
    gl.GetIntegerv(GL_CURRENT_PROGRAM, &prog); gl.GetIntegerv(GL_ACTIVE_TEXTURE, &atex); gl.ActiveTexture(GL_TEXTURE0);
    gl.GetIntegerv(GL_TEXTURE_BINDING_2D, &tex0); gl.GetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
    gl.GetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &dfb); gl.GetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &rfb); gl.GetIntegerv(GL_VIEWPORT, vp);
    gl.GetBooleanv(GL_COLOR_WRITEMASK, cm); if (gl.BindSampler) gl.GetIntegerv(GL_SAMPLER_BINDING, &smp);
    GLenum caps[] = { GL_SCISSOR_TEST, GL_BLEND, GL_DEPTH_TEST, GL_STENCIL_TEST, GL_CULL_FACE, GL_FRAMEBUFFER_SRGB }; GLboolean en[6];
    int ncaps = st->es ? 5 : 6;
    for (int i = 0; i < ncaps; i++) { en[i] = gl.IsEnabled(caps[i]); gl.Disable(caps[i]); }
    gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, 0); gl.BindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    if (gl.ReadBuffer) { gl.GetIntegerv(GL_READ_BUFFER, &rbuf); gl.ReadBuffer(GL_BACK); }
    // copy back buffer -> texture, draw it back through the key shader
    gl.BindTexture(GL_TEXTURE_2D, st->tex); if (gl.BindSampler) gl.BindSampler(0, 0);
    gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST); gl.TexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    gl.CopyTexImage2D(GL_TEXTURE_2D, 0, st->es ? GL_RGBA : GL_RGBA8, 0, 0, w, h, 0);
    gl.UseProgram(st->prog);
    gl.Uniform1i(gl.GetUniformLocation(st->prog, "t"), 0); gl.Uniform1i(gl.GetUniformLocation(st->prog, "N"), nkeys);
    gl.Uniform1f(gl.GetUniformLocation(st->prog, "tol"), tol); gl.Uniform1f(gl.GetUniformLocation(st->prog, "snap"), snap);
    gl.Uniform3fv(gl.GetUniformLocation(st->prog, "K"), nkeys, keys); gl.Uniform1fv(gl.GetUniformLocation(st->prog, "A"), nkeys, alphas);
    gl.BindVertexArray(st->vao); gl.Viewport(0, 0, w, h); gl.ColorMask(1, 1, 1, 1);
    gl.DrawArrays(GL_TRIANGLES, 0, 3);
    // restore
    gl.ColorMask(cm[0], cm[1], cm[2], cm[3]); gl.BindVertexArray(vao); gl.UseProgram(prog); gl.BindTexture(GL_TEXTURE_2D, tex0);
    if (gl.BindSampler) gl.BindSampler(0, smp); gl.ActiveTexture(atex);
    if (gl.ReadBuffer) gl.ReadBuffer(rbuf);
    gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, dfb); gl.BindFramebuffer(GL_READ_FRAMEBUFFER, rfb); gl.Viewport(vp[0], vp[1], vp[2], vp[3]);
    for (int i = 0; i < ncaps; i++) if (en[i]) gl.Enable(caps[i]);
    pthread_mutex_unlock(&mu);
    static int once; if (!once++) LOG("first pass done %dx%d", w, h);
}

#include <time.h>
#include <errno.h>
static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec / 1e6; }
/* pace + key + trace, shared by the three swap entry points. Runs on the app's render thread(s).
 * The cap is per process: each swap reserves the next free slot (last + 1/MAXFPS) under a lock and
 * sleeps outside it, so two windows or threads share the rate instead of each getting it. */
static double min_gap, last_swap; static FILE *trace_f;
static pthread_once_t swap_once = PTHREAD_ONCE_INIT; static pthread_mutex_t swap_mu = PTHREAD_MUTEX_INITIALIZER;
static void swap_init(void) {
    const char *e = getenv("APPGLASS_MAXFPS"); double f = e ? strtod(e, NULL) : 0; min_gap = f > 0 ? 1000.0 / f : 0;
    e = getenv("APPGLASS_TRACE"); if (e && *e) trace_f = fopen(e, "ae");   /* "e": O_CLOEXEC, children do not inherit it */
}
static void pre_swap(EGLDisplay d, EGLSurface s) {
    pthread_once(&swap_once, swap_init);
    double t0 = now_ms();
    pthread_mutex_lock(&swap_mu);
    double prev = last_swap, at = t0;
    if (min_gap > 0 && prev > 0 && at - prev < min_gap) at = prev + min_gap;
    last_swap = at;
    pthread_mutex_unlock(&swap_mu);
    if (at > t0) {
        double w = at - t0; struct timespec ts = { (time_t)(w / 1e3), (long)(((long long)(w * 1e6)) % 1000000000LL) };
        while (nanosleep(&ts, &ts) && errno == EINTR) ;
        t0 = now_ms();
    }
    pass(d, s);
    double t1 = now_ms();
    if (trace_f) { fprintf(trace_f, "%.2f %.2f %.2f\n", t0, prev > 0 ? t0 - prev : 0, t1 - t0); fflush(trace_f); }
}
EGLBoolean eglSwapBuffers(EGLDisplay d, EGLSurface s) { resolve(); pre_swap(d, s); return r_swap(d, s); }
static EGLBoolean swap_ext(EGLDisplay d, EGLSurface s, const EGLint *r, EGLint n) { pre_swap(d, s); return r_swap_ext(d, s, r, n); }
static EGLBoolean swap_khr(EGLDisplay d, EGLSurface s, const EGLint *r, EGLint n) { pre_swap(d, s); return r_swap_khr(d, s, r, n); }

EGLBoolean eglSwapBuffers(EGLDisplay, EGLSurface);
__eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *);
static void *wrap(const char *n, void *real) {
    if (!real || !n || real == (void *)eglSwapBuffers || real == (void *)eglGetProcAddress) return real;
    if (!strcmp(n, "eglSwapBuffers")) { r_swap = (swap_fn)real; return (void *)eglSwapBuffers; }
    if (!strcmp(n, "eglSwapBuffersWithDamageEXT")) { r_swap_ext = (swapd_fn)real; return (void *)swap_ext; }
    if (!strcmp(n, "eglSwapBuffersWithDamageKHR")) { r_swap_khr = (swapd_fn)real; return (void *)swap_khr; }
    if (!strcmp(n, "eglGetProcAddress")) { r_gpa = (gpa_fn)real; return (void *)eglGetProcAddress; }
    return real;
}
__eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *n) {
    resolve();
    return (__eglMustCastToProperFunctionPointerType)wrap(n, (void *)r_gpa(n));
}
static void *wrap_wl(const char *n, void *real);
void *dlsym(void *h, const char *n) {
    void *p = real_dlsym(h, n);
    if (n && n[0] == 'e' && n[1] == 'g' && n[2] == 'l') { void *q = wrap(n, p); if (q != p) LOG("dlsym %s hooked", n); return q; }
    if (n && !strncmp(n, "wl_proxy_marshal_array", 22)) { void *q = wrap_wl(n, p); if (q != p) LOG("dlsym %s hooked", n); return q; }
    return p;
}

/* ---------------- opaque region (see the header) ----------------
 * Every libwayland-client request goes through one of these three exported functions: the
 * variadic wl_proxy_marshal*() and wl_proxy_marshal_array() call them through libwayland's own
 * PLT (checked on Fedora's libwayland-client 1.26: wl_proxy_marshal_flags and the two constructors
 * reach wl_proxy_marshal_array_flags@plt), so a preloaded definition catches C clients (GTK) and
 * dlopen()ed ones (Rust wayland-sys with dlopen) alike. A client that dlsym()s one of the three
 * array functions gets the hook too (wrap_wl), so a libwayland built without that PLT hop still
 * goes through it for those; the variadic ones are left to the PLT (no portable way to forward
 * a va_list to them). Only wl_surface opcode 4 (set_opaque_region) is touched, and only while
 * keys are set. */
#include <stdint.h>
struct wl_proxy; struct wl_interface;
union wl_argument { int32_t i; uint32_t u; int32_t f; const char *s; void *o; uint32_t n; void *a; int32_t h; };
#define WL_SURFACE_SET_OPAQUE_REGION 4
static void *wl_lib(void) {
    static void *h; if (!h) h = dlopen("libwayland-client.so.0", RTLD_LAZY | RTLD_NOLOAD);
    return h;
}
static void *wl_real(const char *n) {
    void *p = wl_lib() ? real_dlsym(wl_lib(), n) : NULL;
    return p ? p : real_dlsym(RTLD_NEXT, n);
}
/* the args to send: a copy with the region dropped for set_opaque_region on a wl_surface */
static union wl_argument *opaque_args(struct wl_proxy *p, uint32_t op, union wl_argument *a, union wl_argument *tmp) {
    if (op != WL_SURFACE_SET_OPAQUE_REGION || !a || !a[0].o) return a;
    if (!nkeys_get()) return a;
    static const char *(*cls)(struct wl_proxy *);
    if (!cls) cls = (const char *(*)(struct wl_proxy *))wl_real("wl_proxy_get_class");
    const char *c = cls ? cls(p) : NULL;
    if (!c || strcmp(c, "wl_surface")) return a;
    static int once; if (!once++) LOG("wl_surface.set_opaque_region -> NULL (the keyed pixels are translucent)");
    tmp[0].o = NULL; return tmp;
}
typedef struct wl_proxy *(*mflags_fn)(struct wl_proxy *, uint32_t, const struct wl_interface *, uint32_t, uint32_t, union wl_argument *);
typedef struct wl_proxy *(*mctor_fn)(struct wl_proxy *, uint32_t, union wl_argument *, const struct wl_interface *);
typedef struct wl_proxy *(*mctorv_fn)(struct wl_proxy *, uint32_t, union wl_argument *, const struct wl_interface *, uint32_t);
struct wl_proxy *wl_proxy_marshal_array_flags(struct wl_proxy *p, uint32_t op, const struct wl_interface *i, uint32_t v, uint32_t fl, union wl_argument *a) {
    static mflags_fn r; if (!r) r = (mflags_fn)wl_real("wl_proxy_marshal_array_flags");
    union wl_argument t[1]; return r(p, op, i, v, fl, opaque_args(p, op, a, t));
}
struct wl_proxy *wl_proxy_marshal_array_constructor(struct wl_proxy *p, uint32_t op, union wl_argument *a, const struct wl_interface *i) {
    static mctor_fn r; if (!r) r = (mctor_fn)wl_real("wl_proxy_marshal_array_constructor");
    union wl_argument t[1]; return r(p, op, opaque_args(p, op, a, t), i);
}
struct wl_proxy *wl_proxy_marshal_array_constructor_versioned(struct wl_proxy *p, uint32_t op, union wl_argument *a, const struct wl_interface *i, uint32_t v) {
    static mctorv_fn r; if (!r) r = (mctorv_fn)wl_real("wl_proxy_marshal_array_constructor_versioned");
    union wl_argument t[1]; return r(p, op, opaque_args(p, op, a, t), i, v);
}

/* dlsym() of the real array functions (the same ones the hooks forward to) returns the hook */
static void *wrap_wl(const char *n, void *real) {
    if (!real || real != wl_real(n)) return real;
    if (!strcmp(n, "wl_proxy_marshal_array_flags")) return (void *)wl_proxy_marshal_array_flags;
    if (!strcmp(n, "wl_proxy_marshal_array_constructor")) return (void *)wl_proxy_marshal_array_constructor;
    if (!strcmp(n, "wl_proxy_marshal_array_constructor_versioned")) return (void *)wl_proxy_marshal_array_constructor_versioned;
    return real;
}

/* ---------------- child env scrub (APPGLASS_SCRUB) ----------------
 * A launcher (ArtCraft) starts other apps; they must not inherit the shim, its keys or the
 * renderer overrides the wrapper set for the launcher alone. With APPGLASS_SCRUB="VAR VAR ..."
 * set, every exec/posix_spawn of another binary gets an envp without: our .so in LD_PRELOAD, APPGLASS_* and the
 * listed vars. No malloc (a forked child may call exec), only stack buffers. */
#include <spawn.h>
#include <unistd.h>
extern char **environ;
static int scrub_on(void) { static int s = -1; if (s < 0) s = getenv("APPGLASS_SCRUB") != NULL; return s; }
static int listed(const char *e, const char *list) {
    size_t n = strcspn(e, "="); const char *p = list;
    while (p && *p) { while (*p == ' ') p++; size_t m = strcspn(p, " "); if (m && m == n && !strncmp(p, e, n)) return 1; p += m; }
    return 0;
}
/* fills out[] (cap entries incl. NULL); ld is a caller buffer for the rewritten LD_PRELOAD */
static char *const *scrub(char *const *envp, char **out, size_t cap, char *ld, size_t ldcap) {
    if (!envp || !scrub_on()) return envp;
    static char list[1024]; static int got;
    if (!got) { const char *l = getenv("APPGLASS_SCRUB"); snprintf(list, sizeof list, "%s", l ? l : ""); got = 1; }
    size_t k = 0;
    for (size_t i = 0; envp[i] && k + 1 < cap; i++) {
        const char *e = envp[i];
        if (!strncmp(e, "APPGLASS_", 9) || listed(e, list)) continue;
        if (!strncmp(e, "LD_PRELOAD=", 11)) {
            size_t o = snprintf(ld, ldcap, "LD_PRELOAD="); const char *p = e + 11; int any = 0;
            while (*p) { while (*p == ' ' || *p == ':') p++; size_t m = strcspn(p, " :"); if (!m) break;
                if (!memmem(p, m, "appglass-", 9) && o + m + 2 < ldcap) { if (any) ld[o++] = ' '; memcpy(ld + o, p, m); o += m; any = 1; }
                p += m; }
            ld[o] = 0; if (any) out[k++] = ld; continue;
        }
        out[k++] = (char *)e;
    }
    out[k] = NULL; return out;
}
/* the launcher re-execs itself once at startup: that exec keeps the env (or it would lose its glass) */
#include <sys/stat.h>
static int is_self(const char *f) {
    struct stat a, b; if (!f || !strchr(f, '/')) return 0;
    return !stat(f, &a) && !stat("/proc/self/exe", &b) && a.st_dev == b.st_dev && a.st_ino == b.st_ino;
}
/* APPGLASS_KEEP="/abs/path ...": the app binary a wrapper script execs (flatpak /app/bin/subl ->
 * /app/extra/sublime_text/sublime_text). That exec keeps the shim; it is the app, not a child. */
static int is_kept(const char *f) {
    const char *l = getenv("APPGLASS_KEEP"); if (!f || f[0] != '/' || !l) return 0;
    size_t n = strlen(f); const char *p = l;
    while (*p) { while (*p == ' ') p++; size_t m = strcspn(p, " "); if (m == n && !strncmp(p, f, n)) return 1; p += m; }
    return 0;
}
static size_t envc(char *const *e) { size_t n = 0; while (e && e[n]) n++; return n + 1; }
#define SCRUBBED(envp, name) if (dbg()) { static const char m[] = "[appglass-ck] exec/spawn: "; write(2, m, sizeof m - 1); write(2, f, strlen(f)); { const char *w = is_self(f) ? " (self)" : is_kept(f) ? " (kept)" : " (other)"; write(2, w, strlen(w)); } for (size_t q = 0; envp && envp[q]; q++) if (!strncmp(envp[q], "LD_PRELOAD=", 11) || !strncmp(envp[q], "WGPU_", 5) || !strncmp(envp[q], "APPGLASS_SCRUB", 14)) { write(2, " ", 1); write(2, envp[q], strcspn(envp[q], "=")); } write(2, "\n", 1); } size_t name##_n = envc(envp); char *name##_v[name##_n]; char name##_ld[4096]; \
    char *const *name = !scrub_on() || is_self(f) || is_kept(f) ? envp : scrub(envp, name##_v, name##_n, name##_ld, sizeof name##_ld)
typedef int (*execve_fn)(const char *, char *const[], char *const[]);
int execve(const char *f, char *const a[], char *const e[]) {
    static execve_fn r; if (!r) r = (execve_fn)real_dlsym(RTLD_NEXT, "execve"); SCRUBBED(e, ne); return r(f, a, ne);
}
int execvpe(const char *f, char *const a[], char *const e[]) {
    static execve_fn r; if (!r) r = (execve_fn)real_dlsym(RTLD_NEXT, "execvpe"); SCRUBBED(e, ne); return r(f, a, ne);
}
int execv(const char *f, char *const a[]) { return execve(f, a, environ); }
int execvp(const char *f, char *const a[]) { return execvpe(f, a, environ); }
typedef int (*spawn_fn)(pid_t *, const char *, const posix_spawn_file_actions_t *, const posix_spawnattr_t *, char *const[], char *const[]);
int posix_spawn(pid_t *p, const char *f, const posix_spawn_file_actions_t *fa, const posix_spawnattr_t *at, char *const a[], char *const e[]) {
    static spawn_fn r; if (!r) r = (spawn_fn)real_dlsym(RTLD_NEXT, "posix_spawn"); SCRUBBED(e, ne); return r(p, f, fa, at, a, ne);
}
int posix_spawnp(pid_t *p, const char *f, const posix_spawn_file_actions_t *fa, const posix_spawnattr_t *at, char *const a[], char *const e[]) {
    static spawn_fn r; if (!r) r = (spawn_fn)real_dlsym(RTLD_NEXT, "posix_spawnp"); SCRUBBED(e, ne); return r(p, f, fa, at, a, ne);
}
/* glibc 2.39+; Rust's Command may use it. Absent from older runtimes: ENOSYS like a libc without it. */
typedef int (*pidfd_spawn_fn)(int *, const char *, const posix_spawn_file_actions_t *, const posix_spawnattr_t *, char *const[], char *const[]);
#include <errno.h>
int pidfd_spawn(int *p, const char *f, const posix_spawn_file_actions_t *fa, const posix_spawnattr_t *at, char *const a[], char *const e[]) {
    static pidfd_spawn_fn r; if (!r) r = (pidfd_spawn_fn)real_dlsym(RTLD_NEXT, "pidfd_spawn"); if (!r) return ENOSYS;
    SCRUBBED(e, ne); return r(p, f, fa, at, a, ne);
}
int pidfd_spawnp(int *p, const char *f, const posix_spawn_file_actions_t *fa, const posix_spawnattr_t *at, char *const a[], char *const e[]) {
    static pidfd_spawn_fn r; if (!r) r = (pidfd_spawn_fn)real_dlsym(RTLD_NEXT, "pidfd_spawnp"); if (!r) return ENOSYS;
    SCRUBBED(e, ne); return r(p, f, fa, at, a, ne);
}

/* glibc's execl*, fexecve, system and popen reach the kernel through its internal __execve and
 * __posix_spawn, past the hooks above. The execl family is rebuilt on the hooked execve/execvp;
 * with the scrub on, system/popen are reimplemented on the hooked posix_spawn of /bin/sh. */
#include <stdarg.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/wait.h>
#define LARGS(a0, argv, then) va_list ap; size_t n = 1; va_start(ap, a0); while (va_arg(ap, char *)) n++; va_end(ap); \
    char *argv[n + 1]; argv[0] = (char *)a0; va_start(ap, a0); for (size_t i = 1; i <= n; i++) argv[i] = va_arg(ap, char *); then; va_end(ap)
int execl(const char *f, const char *a0, ...) { LARGS(a0, v, (void)0); return execve(f, v, environ); }
int execlp(const char *f, const char *a0, ...) { LARGS(a0, v, (void)0); return execvp(f, v); }
int execle(const char *f, const char *a0, ...) {
    char *const *e; LARGS(a0, v, e = va_arg(ap, char *const *)); return execve(f, v, e);
}
int fexecve(int fd, char *const a[], char *const e[]) {
    static int (*r)(int, char *const[], char *const[]); if (!r) r = (int (*)(int, char *const[], char *const[]))real_dlsym(RTLD_NEXT, "fexecve");
    char f[32]; snprintf(f, sizeof f, "/proc/self/fd/%d", fd); SCRUBBED(e, ne); return r(fd, a, ne);
}
static int wait_child(pid_t pid) {
    int st; pid_t w; do w = waitpid(pid, &st, 0); while (w < 0 && errno == EINTR);
    return w < 0 ? -1 : st;
}
int system(const char *cmd) {
    static int (*r)(const char *); if (!r) r = (int (*)(const char *))real_dlsym(RTLD_NEXT, "system");
    if (!cmd || !scrub_on()) return r(cmd);
    /* as POSIX system(): the caller ignores SIGINT/SIGQUIT and blocks SIGCHLD while the shell runs */
    struct sigaction ign = { .sa_handler = SIG_IGN }, oint, oquit; sigemptyset(&ign.sa_mask);
    sigset_t chld, omask, def; sigemptyset(&chld); sigaddset(&chld, SIGCHLD); sigemptyset(&def);
    sigprocmask(SIG_BLOCK, &chld, &omask);
    sigaction(SIGINT, &ign, &oint); sigaction(SIGQUIT, &ign, &oquit);
    if (oint.sa_handler != SIG_IGN) sigaddset(&def, SIGINT);
    if (oquit.sa_handler != SIG_IGN) sigaddset(&def, SIGQUIT);
    posix_spawnattr_t at; posix_spawnattr_init(&at);
    posix_spawnattr_setsigdefault(&at, &def); posix_spawnattr_setsigmask(&at, &omask);
    posix_spawnattr_setflags(&at, POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK);
    char *argv[] = {"sh", "-c", (char *)cmd, NULL}; pid_t pid;
    int st = posix_spawn(&pid, "/bin/sh", NULL, &at, argv, environ) ? 127 << 8 : wait_child(pid);
    posix_spawnattr_destroy(&at);
    sigaction(SIGINT, &oint, NULL); sigaction(SIGQUIT, &oquit, NULL); sigprocmask(SIG_SETMASK, &omask, NULL);
    return st;
}
static struct { FILE *f; pid_t pid; } popened[256];
static pthread_mutex_t popen_mu = PTHREAD_MUTEX_INITIALIZER;
FILE *popen(const char *cmd, const char *mode) {
    static FILE *(*r)(const char *, const char *); if (!r) r = (FILE *(*)(const char *, const char *))real_dlsym(RTLD_NEXT, "popen");
    if (!scrub_on()) return r(cmd, mode);
    int rd = 0, wr = 0, ce = 0;
    for (const char *m = mode; m && *m; m++) { if (*m == 'r') rd = 1; else if (*m == 'w') wr = 1; else if (*m == 'e') ce = 1; }
    if (rd == wr || !cmd) { errno = EINVAL; return NULL; }
    pthread_mutex_lock(&popen_mu);
    size_t slot = 0; while (slot < sizeof popened / sizeof *popened && popened[slot].f) slot++;
    FILE *out = NULL; int fd[2];
    if (slot == sizeof popened / sizeof *popened) { errno = EMFILE; goto done; }
    if (pipe2(fd, O_CLOEXEC)) goto done;
    int mine = rd ? fd[0] : fd[1], theirs = rd ? fd[1] : fd[0];
    posix_spawn_file_actions_t fa; posix_spawn_file_actions_init(&fa);
    /* POSIX: the child does not keep the streams of earlier popen() calls */
    for (size_t i = 0; i < sizeof popened / sizeof *popened; i++)
        if (popened[i].f) posix_spawn_file_actions_addclose(&fa, fileno(popened[i].f));
    posix_spawn_file_actions_adddup2(&fa, theirs, rd ? 1 : 0);
    char *argv[] = {"sh", "-c", (char *)cmd, NULL}; pid_t pid;
    int e = posix_spawn(&pid, "/bin/sh", &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa); close(theirs);
    if (e) { close(mine); errno = e; goto done; }
    if (!ce) fcntl(mine, F_SETFD, 0);
    if (!(out = fdopen(mine, rd ? "r" : "w"))) { int s = errno; close(mine); wait_child(pid); errno = s; goto done; }
    popened[slot].f = out; popened[slot].pid = pid;
done:
    pthread_mutex_unlock(&popen_mu); return out;
}
int pclose(FILE *f) {
    static int (*r)(FILE *); if (!r) r = (int (*)(FILE *))real_dlsym(RTLD_NEXT, "pclose");
    pid_t pid = 0;
    pthread_mutex_lock(&popen_mu);
    for (size_t i = 0; i < sizeof popened / sizeof *popened; i++)
        if (popened[i].f == f) { pid = popened[i].pid; popened[i].f = NULL; break; }
    pthread_mutex_unlock(&popen_mu);
    if (!pid) return r(f);
    fclose(f); return wait_child(pid);
}
