// appglass-wk.so: LD_PRELOAD (or GTK_MODULES) shim that turns an installed
// GTK3 + WebKitGTK 4.1 app (Tauri/wry) into a transparent-capable window and
// injects glass CSS/JS into its pages. No app rebuild.
//
//   LD_PRELOAD=/path/appglass-wk.so APPGLASS_CSS=glass.css [APPGLASS_JS=end.js] [APPGLASS_JS_START=start.js] app
//
// What it does, per WebKitWebView, on the first webkit_web_view_load_uri/load_html:
//   1. webkit_web_view_set_background_color(view, rgba(0,0,0,0))  (and every later call is forced to alpha 0)
//   2. toplevel: RGBA visual (if not yet realized) + app-paintable  (what tao does for transparent:true)
//   3. user stylesheet (USER level, all frames) from APPGLASS_CSS, user script from APPGLASS_JS
//   4. with a stylesheet: a small script that sets html.agl-inactive while the page has no focus
//      (the stylesheet fades the content background on it)
// Everything is resolved with dlsym, so in processes without GTK/WebKit
// (WebKitWebProcess, NetworkProcess, helpers) the shim is inert.
// At load (a constructor) it keeps its APPGLASS_* settings and takes them and
// its own LD_PRELOAD entry out of the environment: the UI process does all the
// work, so no child (the WebKit helpers, anything the app runs) inherits the
// shim or the paths; other LD_PRELOAD entries stay.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { double r, g, b, a; } GdkRGBA;
typedef int gboolean;

static int g_dbg;
static char *g_css, *g_js, *g_js_start;   // APPGLASS_CSS, APPGLASS_JS, APPGLASS_JS_START
static int dbg(void) { return g_dbg; }

static char *take(const char *name) {   // the value, out of the environment
    const char *v = getenv(name); char *c = v ? strdup(v) : NULL;
    unsetenv(name); return c;
}

// LD_PRELOAD without the entries named appglass-wk.so (':' or ' ' separated)
static void drop_preload(void) {
    const char *v = getenv("LD_PRELOAD"); if (!v) return;
    char *in = strdup(v), *out = calloc(1, strlen(v) + 1); if (!in || !out) { free(in); free(out); return; }
    for (char *save = NULL, *t = strtok_r(in, ": ", &save); t; t = strtok_r(NULL, ": ", &save)) {
        const char *b = strrchr(t, '/'); b = b ? b + 1 : t;
        if (strcmp(b, "appglass-wk.so") == 0) continue;
        if (*out) strcat(out, ":");
        strcat(out, t);
    }
    if (*out) setenv("LD_PRELOAD", out, 1); else unsetenv("LD_PRELOAD");
    free(in); free(out);
}

__attribute__((constructor)) static void appglass_wk_init(void) {
    char *d = take("APPGLASS_DEBUG"); g_dbg = d != NULL; free(d);
    g_css = take("APPGLASS_CSS"); g_js = take("APPGLASS_JS"); g_js_start = take("APPGLASS_JS_START");
    drop_preload();
}
#define LOG(...) do { if (dbg()) { fprintf(stderr, "[appglass-wk] " __VA_ARGS__); fputc('\n', stderr); } } while (0)

static void *sym(const char *n) { void *p = dlsym(RTLD_DEFAULT, n); if (!p) LOG("missing %s", n); return p; }
static void *next(const char *n) { return dlsym(RTLD_NEXT, n); }

static char *slurp(const char *path) {
    if (!path || !*path) return NULL;
    FILE *f = fopen(path, "rb"); if (!f) { LOG("cannot open %s", path); return NULL; }
    fseek(f, 0, SEEK_END); long n = ftell(f); rewind(f);
    char *b = malloc(n + 1); if (!b) { fclose(f); return NULL; }
    b[fread(b, 1, n, f)] = 0; fclose(f); return b;
}

static void real_set_bg(void *view, const GdkRGBA *c) {
    static void (*f)(void *, const GdkRGBA *);
    if (!f) f = next("webkit_web_view_set_background_color");
    if (!f) f = sym("webkit_web_view_set_background_color");
    if (f) f(view, c);
}

void webkit_web_view_set_background_color(void *view, const GdkRGBA *c) {
    GdkRGBA t = { c ? c->r : 0, c ? c->g : 0, c ? c->b : 0, 0 };
    LOG("set_background_color(%g,%g,%g,%g) -> alpha 0", t.r, t.g, t.b, c ? c->a : -1);
    real_set_bg(view, &t);
}

// Top frame only (frames see their own focus); runs once per page at document end. The class follows
// document.hasFocus() after each window focus/blur, so nothing runs between focus changes.
static const char FOCUS_JS[] =
    "(function(){if(window.top!==window||window.__aglFocus)return;window.__aglFocus=1;"
    "var d=document.documentElement,f=function(){setTimeout(function(){d.classList.toggle('agl-inactive',!document.hasFocus())},0)};"
    "window.addEventListener('focus',f);window.addEventListener('blur',f);f();})();";

static void glassify(void *view) {
    static void *(*get_data)(void *, const char *); static void (*set_data)(void *, const char *, void *);
    if (!get_data) { get_data = sym("g_object_get_data"); set_data = sym("g_object_set_data"); }
    if (!get_data || !set_data || get_data(view, "appglass")) return;
    set_data(view, "appglass", (void *)1);

    GdkRGBA clear = { 0, 0, 0, 0 };
    real_set_bg(view, &clear);

    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    gboolean (*is_toplevel)(void *) = sym("gtk_widget_is_toplevel");
    gboolean (*get_realized)(void *) = sym("gtk_widget_get_realized");
    void (*set_paintable)(void *, gboolean) = sym("gtk_widget_set_app_paintable");
    void *(*get_screen)(void *) = sym("gtk_widget_get_screen");
    void *(*rgba_visual)(void *) = sym("gdk_screen_get_rgba_visual");
    void (*set_visual)(void *, void *) = sym("gtk_widget_set_visual");
    void (*queue_draw)(void *) = sym("gtk_widget_queue_draw");
    if (get_toplevel && is_toplevel) {
        void *top = get_toplevel(view);
        if (top && is_toplevel(top)) {
            if (get_realized && !get_realized(top) && get_screen && rgba_visual && set_visual) {
                void *v = rgba_visual(get_screen(top)); if (v) set_visual(top, v);
                LOG("toplevel %p: rgba visual %p", top, v);
            } else LOG("toplevel %p already realized: visual unchanged", top);
            if (set_paintable) set_paintable(top, 1);
            if (queue_draw) queue_draw(top);
        } else LOG("view %p has no toplevel yet", view);
    }

    if (dbg()) { // console.log -> stdout of the web process (lands in the app log)
        void *(*get_settings)(void *) = sym("webkit_web_view_get_settings");
        void (*wc)(void *, gboolean) = sym("webkit_settings_set_enable_write_console_messages_to_stdout");
        if (get_settings && wc) wc(get_settings(view), 1);
    }
    void *(*get_ucm)(void *) = sym("webkit_web_view_get_user_content_manager");
    void *ucm = get_ucm ? get_ucm(view) : NULL;
    if (!ucm) { LOG("no user content manager"); return; }
    char *css = slurp(g_css); int had_css = css != NULL;
    if (css) {
        // webkit_user_style_sheet_new(src, WEBKIT_USER_CONTENT_INJECT_ALL_FRAMES=0, WEBKIT_USER_STYLE_LEVEL_USER=0, allow, block)
        void *(*ss_new)(const char *, int, int, const char *const *, const char *const *) = sym("webkit_user_style_sheet_new");
        void (*add_ss)(void *, void *) = sym("webkit_user_content_manager_add_style_sheet");
        void (*ss_unref)(void *) = sym("webkit_user_style_sheet_unref");
        if (ss_new && add_ss) { void *s = ss_new(css, 0, 0, NULL, NULL); add_ss(ucm, s); if (ss_unref) ss_unref(s); LOG("css injected (%zu bytes)", strlen(css)); }
        free(css);
    }
    // webkit_user_script_new(src, ALL_FRAMES=0, INJECT_AT_DOCUMENT_START=0 / END=1, allow, block)
    void *(*sc_new)(const char *, int, int, const char *const *, const char *const *) = sym("webkit_user_script_new");
    void (*add_sc)(void *, void *) = sym("webkit_user_content_manager_add_script");
    void (*sc_unref)(void *) = sym("webkit_user_script_unref");
    if (!sc_new || !add_sc) return;
    for (int at = 0; at < 2; at++) {  // APPGLASS_JS_START: document start (0); APPGLASS_JS: document end (1)
        char *js = slurp(at ? g_js : g_js_start);
        if (!js) continue;
        void *s = sc_new(js, 0, at, NULL, NULL); add_sc(ucm, s); if (sc_unref) sc_unref(s); LOG("js injected at %s (%zu bytes)", at ? "end" : "start", strlen(js));
        free(js);
    }
    if (had_css) {  // unfocused fade: html.agl-inactive while the page has no focus (the glass CSS eases it)
        void *s = sc_new(FOCUS_JS, 0, 1, NULL, NULL); add_sc(ucm, s); if (sc_unref) sc_unref(s); LOG("focus script injected");
    }
}

void webkit_web_view_load_uri(void *view, const char *uri) {
    static void (*f)(void *, const char *); if (!f) f = next("webkit_web_view_load_uri");
    LOG("load_uri %s", uri ? uri : "(null)");
    glassify(view); f(view, uri);
}

void webkit_web_view_load_html(void *view, const char *html, const char *base) {
    static void (*f)(void *, const char *, const char *); if (!f) f = next("webkit_web_view_load_html");
    glassify(view); f(view, html, base);
}

// GTK_MODULES entry point (absolute path in GTK_MODULES). As a module the PLT
// hooks above do not apply; an emission hook on "map" catches every WebView.
typedef struct { unsigned long g_type; } GTypeInstanceLike;
static gboolean on_map(void *ihint, unsigned n, const void *params, void *data) {
    (void)ihint; (void)n; (void)data;
    void *(*val_get_object)(const void *) = sym("g_value_get_object");
    unsigned long (*wv_type)(void) = sym("webkit_web_view_get_type");
    gboolean (*is_a)(unsigned long, unsigned long) = sym("g_type_is_a");
    if (!val_get_object || !wv_type || !is_a) return 1;
    void *w = val_get_object(params);
    if (w && is_a(((GTypeInstanceLike *)*(void **)w)->g_type, wv_type())) glassify(w);
    return 1;
}
void gtk_module_init(int *argc, char ***argv) {
    (void)argc; (void)argv;
    unsigned long (*widget_type)(void) = sym("gtk_widget_get_type");
    unsigned (*lookup)(const char *, unsigned long) = sym("g_signal_lookup");
    void *(*type_class_ref)(unsigned long) = sym("g_type_class_ref");
    unsigned long (*add_hook)(unsigned, unsigned, void *, void *, void *) = sym("g_signal_add_emission_hook");
    if (!widget_type || !lookup || !add_hook) return;
    type_class_ref(widget_type());
    add_hook(lookup("map", widget_type()), 0, (void *)on_map, NULL, NULL);
    LOG("gtk module loaded");
}
