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
// so the pass is idempotent with buffer-age partial repaints.
//
//   LD_PRELOAD=/path/appglass-ck.so APPGLASS_KEYS="f4fbf8:0.60,e6ede9:0.65" [APPGLASS_TOL=0.02] [APPGLASS_SNAP=0.75] [APPGLASS_DEBUG=1] app
//
// The EGL surface must have an alpha channel (check the wl_buffer format: AR24
// works, XR24 does not). Hooks are reached through the PLT, through dlsym()
// (libepoxy resolves eglSwapBuffers with dlsym on its own libEGL handle) and
// through eglGetProcAddress (the *WithDamage* extensions).
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
static float keys[MAXK * 3], alphas[MAXK]; static int nkeys = -1; static float tol = 0.02f, snap = 0.75f;
static void parse_keys(void) {
    nkeys = 0; const char *s = getenv("APPGLASS_KEYS"); if (!s) return;
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
    if (nkeys < 0) parse_keys();
    if (nkeys == 0) return;
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

EGLBoolean eglSwapBuffers(EGLDisplay d, EGLSurface s) { resolve(); pass(d, s); return r_swap(d, s); }
static EGLBoolean swap_ext(EGLDisplay d, EGLSurface s, const EGLint *r, EGLint n) { pass(d, s); return r_swap_ext(d, s, r, n); }
static EGLBoolean swap_khr(EGLDisplay d, EGLSurface s, const EGLint *r, EGLint n) { pass(d, s); return r_swap_khr(d, s, r, n); }

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
void *dlsym(void *h, const char *n) {
    void *p = real_dlsym(h, n);
    if (n && n[0] == 'e' && n[1] == 'g' && n[2] == 'l') { void *q = wrap(n, p); if (q != p) LOG("dlsym %s hooked", n); return q; }
    return p;
}
