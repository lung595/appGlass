// appglass-wk.so: LD_PRELOAD (or GTK_MODULES) shim that turns an installed
// GTK3 + WebKitGTK 4.1 app (Tauri/wry) into a transparent-capable window and
// injects glass CSS/JS into its pages. No app rebuild.
//
//   LD_PRELOAD=/path/appglass-wk.so APPGLASS_CSS=glass.css [APPGLASS_JS=end.js] [APPGLASS_JS_START=start.js] app
//
// What it does, per WebKitWebView, on the first webkit_web_view_load_uri/html/request/bytes:
//   1. webkit_web_view_set_background_color(view, rgba(0,0,0,0))  (and every later call is forced to alpha 0)
//   2. toplevel: RGBA visual (if not yet realized) + app-paintable  (what tao does for transparent:true),
//      only when the view fills it: when the toplevel maps, no other widget is mapped beside the view
//      or any of its ancestors (a header bar given with gtk_window_set_titlebar is fine: it paints
//      itself). Native chrome around a WebView (a mail client's folder list) would be holes on the
//      bare blur: such a view gets its background back and the window stays opaque.
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

// The environment is edited in the environ array itself, not with
// unsetenv/setenv: a shell (bash) exports its own getenv/setenv/unsetenv,
// which in its constructor do not reach the environ it later builds its
// children from, so a launcher script would pass the shim on.
extern char **environ;

static char **env_find(const char *name) {   // the environ slot of name, or NULL
    size_t n = strlen(name);
    for (char **e = environ; e && *e; e++) if (strncmp(*e, name, n) == 0 && (*e)[n] == '=') return e;
    return NULL;
}

static void env_drop(char **slot) {   // the entry out of the array, the rest moved up
    do slot[0] = slot[1]; while (*slot++);
}

static char *take(const char *name) {   // the value, out of the environment
    char **e, *c = NULL;
    while ((e = env_find(name))) { if (!c) c = strdup(*e + strlen(name) + 1); env_drop(e); }
    return c;
}

// LD_PRELOAD without the entries named appglass-wk.so (':' or ' ' separated)
static void drop_preload(void) {
    char **e = env_find("LD_PRELOAD"); if (!e) return;
    const char *v = *e + strlen("LD_PRELOAD=");
    char *in = strdup(v), *out = calloc(1, strlen("LD_PRELOAD=") + strlen(v) + 1);
    if (!in || !out) { free(in); free(out); return; }
    strcpy(out, "LD_PRELOAD=");
    size_t head = strlen(out);
    for (char *save = NULL, *t = strtok_r(in, ": ", &save); t; t = strtok_r(NULL, ": ", &save)) {
        const char *b = strrchr(t, '/'); b = b ? b + 1 : t;
        if (strcmp(b, "appglass-wk.so") == 0) continue;
        if (strlen(out) > head) strcat(out, ":");
        strcat(out, t);
    }
    free(in);
    if (strlen(out) > head) *e = out;   // kept for the life of the process, as putenv's
    else { free(out); env_drop(e); }
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

static void *obj_get(void *o, const char *k) {
    static void *(*f)(void *, const char *); if (!f) f = sym("g_object_get_data");
    return f ? f(o, k) : NULL;
}
static void obj_set(void *o, const char *k, void *v, void (*destroy)(void *)) {
    static void (*f)(void *, const char *, void *, void (*)(void *)); if (!f) f = sym("g_object_set_data_full");
    if (f) f(o, k, v, destroy); else if (destroy && v) destroy(v);
}

// the app's own colour is kept (appglass-bg): a view left opaque gets it back
void webkit_web_view_set_background_color(void *view, const GdkRGBA *c) {
    if (c) { GdkRGBA *k = malloc(sizeof *k); if (k) { *k = *c; obj_set(view, "appglass-bg", k, free); } }
    if (obj_get(view, "appglass-off")) { real_set_bg(view, c); return; }
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

static void uninject(void *view);

// 1 when nothing but the view is drawn in the toplevel: no other child of the view's ancestors is
// mapped (at the toplevel's map, after its children). A titlebar is not a child (it paints itself).
static int fills(void *view, void *top) {
    void *(*get_parent)(void *) = sym("gtk_widget_get_parent");
    gboolean (*mapped)(void *) = sym("gtk_widget_get_mapped");
    void *(*children)(void *) = sym("gtk_container_get_children");
    void (*list_free)(void *) = sym("g_list_free");
    const char *(*name)(void *) = sym("gtk_widget_get_name");
    if (!get_parent || !mapped || !children || !list_free) return 1;
    typedef struct L { void *data; struct L *next, *prev; } L;
    for (void *w = view; w && w != top; ) {
        void *p = get_parent(w); if (!p) return 0;
        L *l = children(p); int other = 0;
        for (L *i = l; i; i = i->next)
            if (i->data != w && mapped(i->data)) { other = 1; LOG("beside the view: %s", name ? name(i->data) : "?"); break; }
        list_free(l);
        if (other) return 0;
        w = p;
    }
    return 1;
}

// the toplevel is mapped: glass it if the view fills it, else the view gets its background back
static void decide(void *view, void *top) {
    if (obj_get(view, "appglass-decided")) return;
    obj_set(view, "appglass-decided", (void *)1, NULL);
    void (*set_paintable)(void *, gboolean) = sym("gtk_widget_set_app_paintable");
    void (*queue_draw)(void *) = sym("gtk_widget_queue_draw");
    if (fills(view, top)) {
        if (set_paintable) set_paintable(top, 1);
        if (queue_draw) queue_draw(top);
        LOG("toplevel %p: app-paintable (the view fills it)", top);
        return;
    }
    obj_set(view, "appglass-off", (void *)1, NULL);
    const GdkRGBA *k = obj_get(view, "appglass-bg"); GdkRGBA white = { 1, 1, 1, 1 };
    real_set_bg(view, k ? k : &white);
    uninject(view);
    LOG("toplevel %p: native widgets beside the view, left opaque", top);
}
static void on_top_map(void *view, void *top) { decide(view, top); }   // swapped: (view, toplevel)
// the toplevel is mapped already, maybe mapping now (a view seen at its own map): once it is done
static int decide_idle(void *view) {
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    void *top = get_toplevel ? get_toplevel(view) : NULL;
    if (top) decide(view, top);
    return 0;
}

// the window of the view: RGBA visual (before it is realized), then decide() at its map; 0 without one yet
static int glass_toplevel(void *view) {
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    gboolean (*is_toplevel)(void *) = sym("gtk_widget_is_toplevel");
    gboolean (*get_realized)(void *) = sym("gtk_widget_get_realized");
    gboolean (*get_mapped)(void *) = sym("gtk_widget_get_mapped");
    void *(*get_screen)(void *) = sym("gtk_widget_get_screen");
    void *(*rgba_visual)(void *) = sym("gdk_screen_get_rgba_visual");
    void (*set_visual)(void *, void *) = sym("gtk_widget_set_visual");
    unsigned long (*connect_object)(void *, const char *, void *, void *, int) = sym("g_signal_connect_object");
    if (!get_toplevel || !is_toplevel) return 1;   // not GTK3: nothing to wait for
    void *top = get_toplevel(view);
    if (!top || !is_toplevel(top)) { LOG("view %p has no toplevel yet", view); return 0; }
    if (get_realized && !get_realized(top) && get_screen && rgba_visual && set_visual) {
        void *v = rgba_visual(get_screen(top)); if (v) set_visual(top, v);
        LOG("toplevel %p: rgba visual %p", top, v);
    } else LOG("toplevel %p already realized: visual unchanged", top);
    void *(*ref)(void *) = sym("g_object_ref"); void (*unref)(void *) = sym("g_object_unref");
    unsigned (*idle_full)(int, void *, void *, void (*)(void *)) = sym("g_idle_add_full");
    if (get_mapped && get_mapped(top)) {
        if (idle_full && ref && unref) idle_full(0, (void *)decide_idle, ref(view), unref);   // G_PRIORITY_DEFAULT
        else decide(view, top);
    } else if (connect_object)   // G_CONNECT_AFTER | G_CONNECT_SWAPPED: after the children are mapped
        connect_object(top, "map", (void *)on_top_map, view, 1 | 2);
    return 1;
}

static void on_hierarchy(void *view, void *prev, void *data) {
    (void)prev; (void)data;
    if (obj_get(view, "appglass-top")) return;
    if (glass_toplevel(view)) obj_set(view, "appglass-top", (void *)1, NULL);
}

// the stylesheet and scripts added to the view's content manager, kept on the view (its data owns a
// ref) so a view left opaque can take them out again
static const char *const ITEMS[] = { "appglass-ss", "appglass-sc0", "appglass-sc1", "appglass-sc2" };

static void inject(void *view) {
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
        if (ss_new && add_ss) {
            void *ss = ss_new(css, 0, 0, NULL, NULL); add_ss(ucm, ss); obj_set(view, ITEMS[0], ss, ss_unref);
            LOG("css injected (%zu bytes)", strlen(css));
        }
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
        void *sc = sc_new(js, 0, at, NULL, NULL); add_sc(ucm, sc); obj_set(view, ITEMS[1 + at], sc, sc_unref);
        LOG("js injected at %s (%zu bytes)", at ? "end" : "start", strlen(js));
        free(js);
    }
    if (had_css) {  // unfocused fade: html.agl-inactive while the page has no focus (the glass CSS eases it)
        void *sc = sc_new(FOCUS_JS, 0, 1, NULL, NULL); add_sc(ucm, sc); obj_set(view, ITEMS[3], sc, sc_unref);
        LOG("focus script injected");
    }
}

// a view left opaque: what inject() added comes out (the script only set attributes and custom
// properties: without the stylesheet the page is as the app drew it)
static void uninject(void *view) {
    void *(*get_ucm)(void *) = sym("webkit_web_view_get_user_content_manager");
    void (*rm_ss)(void *, void *) = sym("webkit_user_content_manager_remove_style_sheet");
    void (*rm_sc)(void *, void *) = sym("webkit_user_content_manager_remove_script");
    void *ucm = get_ucm ? get_ucm(view) : NULL;
    if (!ucm) return;
    for (unsigned i = 0; i < sizeof ITEMS / sizeof *ITEMS; i++) {
        void *it = obj_get(view, ITEMS[i]); if (!it) continue;
        if (i == 0 && rm_ss) rm_ss(ucm, it); else if (i && rm_sc) rm_sc(ucm, it);
        obj_set(view, ITEMS[i], NULL, NULL);   // drops the ref
    }
    LOG("glass stylesheet and scripts removed");
}

static void glassify(void *view) {
    if (obj_get(view, "appglass")) return;
    obj_set(view, "appglass", (void *)1, NULL);
    GdkRGBA clear = { 0, 0, 0, 0 };
    real_set_bg(view, &clear);
    inject(view);
    if (!glass_toplevel(view)) {  // not in a window yet (wry builds the view first): when it is
        unsigned long (*connect)(void *, const char *, void *, void *, void *, int) = sym("g_signal_connect_data");
        if (connect) connect(view, "hierarchy-changed", (void *)on_hierarchy, NULL, NULL, 0);
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

// the other first loads an app may use (any WebKitGTK app, not only Tauri/wry)
void webkit_web_view_load_request(void *view, void *req) {
    static void (*f)(void *, void *); if (!f) f = next("webkit_web_view_load_request");
    glassify(view); f(view, req);
}

void webkit_web_view_load_alternate_html(void *view, const char *html, const char *uri, const char *base) {
    static void (*f)(void *, const char *, const char *, const char *);
    if (!f) f = next("webkit_web_view_load_alternate_html");
    glassify(view); f(view, html, uri, base);
}

void webkit_web_view_load_bytes(void *view, void *bytes, const char *mime, const char *enc, const char *base) {
    static void (*f)(void *, void *, const char *, const char *, const char *);
    if (!f) f = next("webkit_web_view_load_bytes");
    glassify(view); f(view, bytes, mime, enc, base);
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
