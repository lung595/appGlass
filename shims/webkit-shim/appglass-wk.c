// appglass-wk.so: LD_PRELOAD (or GTK_MODULES) shim that turns an installed
// GTK3 + WebKitGTK 4.1 app (Tauri/wry) into a transparent-capable window and
// injects glass CSS/JS into its pages. No app rebuild.
//
//   LD_PRELOAD=/path/appglass-wk.so APPGLASS_CSS=glass.css [APPGLASS_JS=end.js] [APPGLASS_JS_START=start.js] app
//
// What it does, per WebKitWebView, on the first webkit_web_view_load_uri/html/request/bytes:
//   1. webkit_web_view_set_background_color(view, rgba(0,0,0,0))  (and every later call is forced to alpha 0)
//   2. toplevel: RGBA visual (if not yet realized) + app-paintable  (what tao does for transparent:true),
//      only while the view fills it: no other widget is mapped beside the view or any of its
//      ancestors (a GtkHeaderBar given with gtk_window_set_titlebar is fine: it paints itself;
//      any other custom titlebar counts, a plain box is clear in a CSD window).
//      Looked at, for every view of the window (a stack of views: the one shown can fill it),
//      when the toplevel maps, whenever a widget in it maps or unmaps (an emission hook, once
//      the main loop is idle) and at a view's first document: native chrome around a WebView (a mail
//      client's folder list, a sidebar shown later) would be holes on the bare blur, so the view
//      gets its background back, the stylesheet comes out and the window is opaque; when the
//      chrome is gone again, the glass comes back. The scripts stay in all along: they only mark
//      the page (inert without the stylesheet), and a user script runs only on a document that
//      loads after it is added, so a page loaded while opaque would come back unmarked (bare).
//   3. user stylesheet (USER level, all frames) from APPGLASS_CSS, user script from APPGLASS_JS
//   4. with a stylesheet: a small script that sets html.agl-inactive while the page has no focus
//      (the stylesheet fades the content background on it)
// Everything is resolved with dlsym, so in processes without GTK/WebKit
// (WebKitWebProcess, NetworkProcess, helpers) the shim is inert.
// At load (a constructor) it keeps its APPGLASS_* settings and takes every
// APPGLASS_* variable (its own, the hidden check's, the e2e's) and its own
// LD_PRELOAD entry out of the environment: the UI process does all the work,
// so no child (the WebKit helpers, anything the app runs) inherits the shim or
// the paths; other LD_PRELOAD entries stay.
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

// LD_PRELOAD without the entries named appglass-wk.so (':' or ' ' separated), in every LD_PRELOAD
// slot of the array (execve takes one with the name twice)
static void drop_preload(void) {
    const size_t pre = strlen("LD_PRELOAD=");
    for (char **e = environ; e && *e; ) {
        if (strncmp(*e, "LD_PRELOAD=", pre) != 0) { e++; continue; }
        const char *v = *e + pre;
        char *in = strdup(v), *out = calloc(1, pre + strlen(v) + 1);
        if (!in || !out) { free(in); free(out); return; }
        strcpy(out, "LD_PRELOAD=");
        for (char *save = NULL, *t = strtok_r(in, ": ", &save); t; t = strtok_r(NULL, ": ", &save)) {
            const char *b = strrchr(t, '/'); b = b ? b + 1 : t;
            if (strcmp(b, "appglass-wk.so") == 0) continue;
            if (strlen(out) > pre) strcat(out, ":");
            strcat(out, t);
        }
        free(in);
        if (strlen(out) > pre) { *e = out; e++; }   // kept for the life of the process, as putenv's
        else { free(out); env_drop(e); }            // the next entry moved up into this slot
    }
}

__attribute__((constructor)) static void appglass_wk_init(void) {
    char *d = take("APPGLASS_DEBUG"); g_dbg = d != NULL; free(d);
    g_css = take("APPGLASS_CSS"); g_js = take("APPGLASS_JS"); g_js_start = take("APPGLASS_JS_START");
    for (char **e = environ; e && *e; ) {   // the rest of APPGLASS_* (none is the app's)
        if (strncmp(*e, "APPGLASS_", 9) == 0) env_drop(e); else e++;
    }
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

static void remove_sheet(void *view);

// a frame of the bare window round w: its margins, or the border-width of a container (CSS padding
// is not looked at)
static int framed(void *w, int container) {
    static const char *const M[] = { "gtk_widget_get_margin_start", "gtk_widget_get_margin_end",
                                     "gtk_widget_get_margin_top", "gtk_widget_get_margin_bottom" };
    unsigned (*border)(void *) = sym("gtk_container_get_border_width");
    if (container && border && border(w)) return 1;
    for (int i = 0; i < 4 && !container; i++) {
        int (*m)(void *) = sym(M[i]);
        if (m && m(w)) return 1;
    }
    return 0;
}

// the window's custom titlebar when it is a GtkHeaderBar (it paints its own background), else NULL
static void *header_bar(void *top) {
    void *(*get_titlebar)(void *) = sym("gtk_window_get_titlebar");
    unsigned long (*hb_type)(void) = sym("gtk_header_bar_get_type");
    gboolean (*is_a)(void *, unsigned long) = sym("g_type_check_instance_is_a");
    void *t = get_titlebar && hb_type && is_a ? get_titlebar(top) : NULL;
    return t && is_a(t, hb_type()) ? t : NULL;
}

// 1 when nothing but the view is drawn in the toplevel: no other child of the view's ancestors is
// mapped (at the toplevel's map, after its children), and no margin or border-width leaves a frame
// round it. GTK3 lists a custom titlebar among the window's children: a GtkHeaderBar does not count
// (it paints itself), any other titlebar does.
static int fills(void *view, void *top) {
    void *(*get_parent)(void *) = sym("gtk_widget_get_parent");
    gboolean (*mapped)(void *) = sym("gtk_widget_get_mapped");
    void *(*children)(void *) = sym("gtk_container_get_children");
    void (*list_free)(void *) = sym("g_list_free");
    const char *(*name)(void *) = sym("gtk_widget_get_name");
    if (!get_parent || !mapped || !children || !list_free) return 1;
    typedef struct L { void *data; struct L *next, *prev; } L;
    void *hb = header_bar(top);
    for (void *w = view; w && w != top; ) {
        void *p = get_parent(w); if (!p) return 0;
        if (framed(w, 0) || framed(p, 1)) { LOG("a frame round the view"); return 0; }
        L *l = children(p); int other = 0;
        for (L *i = l; i; i = i->next)
            if (i->data != w && !(p == top && i->data == hb) && mapped(i->data)) {
                other = 1; LOG("beside the view: %s", name ? name(i->data) : "?"); break;
            }
        list_free(l);
        if (other) return 0;
        w = p;
    }
    return 1;
}

static int add_sheet(void *view);

// a view's glass on (the view clear, the page styled) or off (the view's own background, the
// stylesheet out). The state is kept on the view (appglass-state: 1 glass, 2 opaque; none yet: the
// view clear and the page styled since its first load). The window is not touched here: see
// set_window().
static void set_glass(void *view, int on) {
    long st = (long)obj_get(view, "appglass-state");
    if (st == (on ? 1 : 2)) return;
    obj_set(view, "appglass-state", (void *)(long)(on ? 1 : 2), NULL);
    if (on && st == 2) {   // opaque before: the page glass again
        obj_set(view, "appglass-off", NULL, NULL);
        GdkRGBA clear = { 0, 0, 0, 0 };
        real_set_bg(view, &clear);
        add_sheet(view);
    } else if (!on) {
        obj_set(view, "appglass-off", (void *)1, NULL);
        const GdkRGBA *k = obj_get(view, "appglass-bg"); GdkRGBA white = { 1, 1, 1, 1 };
        real_set_bg(view, k ? k : &white);
        remove_sheet(view);
    }
}

// The views of a toplevel (appglass-views on it): weak refs, so a view that goes away drops out. A
// window with more views than VIEWS is never glassed.
enum { VIEWS = 16 };
typedef struct { int n, many; void *wr[VIEWS]; } Views;   // GWeakRef: one pointer
static void views_free(void *p) {
    Views *vs = p; void (*clear)(void *) = sym("g_weak_ref_clear");
    for (int i = 0; i < vs->n && clear; i++) clear(&vs->wr[i]);
    free(vs);
}
// view i of top (a ref, or NULL: gone, or now in another window)
static void *view_at(void *top, Views *vs, int i) {
    void *(*get)(void *) = sym("g_weak_ref_get"); void (*unref)(void *) = sym("g_object_unref");
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    void *v = get ? get(&vs->wr[i]) : NULL;
    if (v && (!get_toplevel || get_toplevel(v) != top)) { if (unref) unref(v); v = NULL; }
    return v;
}

// the window app-paintable while one of its views is glass and shows its first document (before,
// the clear view would show the bare blur): at most one view fills the window at a time (another
// view mapped is a widget beside it). Left alone until a view of it is decided.
static void set_window(void *top) {
    void (*set_paintable)(void *, gboolean) = sym("gtk_widget_set_app_paintable");
    void (*queue_draw)(void *) = sym("gtk_widget_queue_draw");
    void (*unref)(void *) = sym("g_object_unref");
    Views *vs = obj_get(top, "appglass-views");
    if (!vs) return;
    int decided = 0, on = 0, wait = 0;
    for (int i = 0; i < vs->n; i++) {
        void *v = view_at(top, vs, i);
        if (!v) continue;
        long st = (long)obj_get(v, "appglass-state");
        decided |= st != 0;
        if (st == 1) { if (obj_get(v, "appglass-shown")) on = 1; else wait = 1; }
        if (unref) unref(v);
    }
    if (!decided) return;
    if (vs->many) on = 0;
    long want = on ? 1 : 2;
    if ((long)obj_get(top, "appglass-paint") == want) return;
    obj_set(top, "appglass-paint", (void *)want, NULL);
    if (set_paintable) set_paintable(top, on);
    if (queue_draw) queue_draw(top);
    if (on) LOG("toplevel %p: app-paintable (the view fills it)", top);
    else if (wait) LOG("toplevel %p: the view fills it, app-paintable at the first document", top);
    else LOG("toplevel %p: native widgets beside the view, left opaque", top);
}

// every view of the mapped window decided afresh (glass while it fills the window), then the
// window: at each map of the window, whenever a widget in it maps or unmaps (a sidebar shown after
// the map, a pane hidden after show_all, another page of a stack), and at a view's first document
static void redecide(void *top) {
    gboolean (*mapped)(void *) = sym("gtk_widget_get_mapped");
    void (*unref)(void *) = sym("g_object_unref");
    Views *vs = obj_get(top, "appglass-views");
    if (!vs || !mapped || !mapped(top)) return;
    for (int i = 0; i < vs->n; i++) {
        void *v = view_at(top, vs, i);
        if (!v) continue;
        set_glass(v, fills(v, top));
        if (unref) unref(v);
    }
    set_window(top);
}
static void on_top_map(void *top, void *data) { (void)data; redecide(top); }
static int redecide_idle(void *top) {
    obj_set(top, "appglass-pending", NULL, NULL);
    redecide(top);
    return 0;
}
// once the main loop is idle again (one idle per window, however many widgets map)
static void redecide_later(void *top) {
    void *(*ref)(void *) = sym("g_object_ref"); void (*unref)(void *) = sym("g_object_unref");
    unsigned (*idle_full)(int, void *, void *, void (*)(void *)) = sym("g_idle_add_full");
    if (obj_get(top, "appglass-pending")) return;
    if (!ref || !unref || !idle_full) { redecide(top); return; }
    obj_set(top, "appglass-pending", (void *)1, NULL);
    idle_full(0, (void *)redecide_idle, ref(top), unref);   // G_PRIORITY_DEFAULT
}
// emission hook on every widget's map and unmap: a widget in a tracked window re-decides it
static gboolean on_widget_map(void *ihint, unsigned n, const void *params, void *data) {
    (void)ihint; (void)n; (void)data;
    void *(*val_get_object)(const void *) = sym("g_value_get_object");
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    if (!val_get_object || !get_toplevel) return 1;
    void *w = val_get_object(params);
    void *top = w ? get_toplevel(w) : NULL;
    if (top && obj_get(top, "appglass-views")) redecide_later(top);
    return 1;
}
// the view in the toplevel's list (the window's map handler once per window), the hooks once
static void track(void *view, void *top) {
    static int hooked;
    void (*init)(void *, void *) = sym("g_weak_ref_init");
    void *(*get)(void *) = sym("g_weak_ref_get"); void (*unref)(void *) = sym("g_object_unref");
    unsigned long (*connect)(void *, const char *, void *, void *, void *, int) = sym("g_signal_connect_data");
    if (!init || !get || !unref) return;
    Views *vs = obj_get(top, "appglass-views");
    if (!vs) {
        if (!(vs = calloc(1, sizeof *vs))) return;
        obj_set(top, "appglass-views", vs, views_free);
        if (connect)   // G_CONNECT_AFTER: after the children are mapped
            connect(top, "map", (void *)on_top_map, NULL, NULL, 1);
    }
    int had = 0, free_slot = -1;
    for (int i = 0; i < vs->n && !had; i++) {
        void *v = get(&vs->wr[i]);
        if (v == view) had = 1;
        else if (!v && free_slot < 0) free_slot = i;
        if (v) unref(v);
    }
    if (!had) {
        if (free_slot >= 0) init(&vs->wr[free_slot], view);
        else if (vs->n < VIEWS) init(&vs->wr[vs->n++], view);
        else { vs->many = 1; LOG("toplevel %p: more than %d views, left opaque", top, VIEWS); }
    }
    if (hooked) return;
    unsigned long (*widget_type)(void) = sym("gtk_widget_get_type");
    unsigned (*lookup)(const char *, unsigned long) = sym("g_signal_lookup");
    unsigned long (*add_hook)(unsigned, unsigned, void *, void *, void *) = sym("g_signal_add_emission_hook");
    if (!widget_type || !lookup || !add_hook) return;
    hooked = 1;
    add_hook(lookup("map", widget_type()), 0, (void *)on_widget_map, NULL, NULL);
    add_hook(lookup("unmap", widget_type()), 0, (void *)on_widget_map, NULL, NULL);
}

// the window of the view: RGBA visual (before it is realized), then redecide() at each of its maps
// and whenever a widget in it maps or unmaps; 0 without one yet
static int glass_toplevel(void *view) {
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    gboolean (*is_toplevel)(void *) = sym("gtk_widget_is_toplevel");
    gboolean (*get_realized)(void *) = sym("gtk_widget_get_realized");
    gboolean (*get_mapped)(void *) = sym("gtk_widget_get_mapped");
    void *(*get_screen)(void *) = sym("gtk_widget_get_screen");
    void *(*rgba_visual)(void *) = sym("gdk_screen_get_rgba_visual");
    void (*set_visual)(void *, void *) = sym("gtk_widget_set_visual");
    if (!get_toplevel || !is_toplevel) return 1;   // not GTK3: nothing to wait for
    void *top = get_toplevel(view);
    if (!top || !is_toplevel(top)) { LOG("view %p has no toplevel yet", view); return 0; }
    if (get_realized && !get_realized(top) && get_screen && rgba_visual && set_visual) {
        void *v = rgba_visual(get_screen(top)); if (v) set_visual(top, v);
        LOG("toplevel %p: rgba visual %p", top, v);
    } else LOG("toplevel %p already realized: visual unchanged", top);
    track(view, top);
    // mapped already, maybe mapping now (a view seen at its own map): once it is done
    if (get_mapped && get_mapped(top)) redecide_later(top);
    return 1;
}

static void on_hierarchy(void *view, void *prev, void *data) {
    (void)prev; (void)data;
    if (obj_get(view, "appglass-top")) return;
    if (glass_toplevel(view)) obj_set(view, "appglass-top", (void *)1, NULL);
}

// the stylesheet and scripts added to the view's content manager, kept on the view (its data owns a
// ref): the stylesheet comes out while the view is left opaque, the scripts stay
static const char *const ITEMS[] = { "appglass-ss", "appglass-sc0", "appglass-sc1", "appglass-sc2" };

static void *content_manager(void *view) {
    void *(*get_ucm)(void *) = sym("webkit_web_view_get_user_content_manager");
    void *ucm = get_ucm ? get_ucm(view) : NULL;
    if (!ucm) LOG("no user content manager");
    return ucm;
}

// the glass stylesheet (APPGLASS_CSS) in, once: 1 when there is one
static int add_sheet(void *view) {
    void *ucm = content_manager(view);
    if (!ucm || obj_get(view, ITEMS[0])) return ucm != NULL;
    char *css = slurp(g_css);
    if (!css) return 0;
    // webkit_user_style_sheet_new(src, WEBKIT_USER_CONTENT_INJECT_ALL_FRAMES=0, WEBKIT_USER_STYLE_LEVEL_USER=0, allow, block)
    void *(*ss_new)(const char *, int, int, const char *const *, const char *const *) = sym("webkit_user_style_sheet_new");
    void (*add_ss)(void *, void *) = sym("webkit_user_content_manager_add_style_sheet");
    void (*ss_unref)(void *) = sym("webkit_user_style_sheet_unref");
    if (ss_new && add_ss) {
        void *ss = ss_new(css, 0, 0, NULL, NULL); add_ss(ucm, ss); obj_set(view, ITEMS[0], ss, ss_unref);
        LOG("css injected (%zu bytes)", strlen(css));
    }
    free(css);
    return 1;
}

// a view left opaque: the stylesheet out (the scripts only set attributes, a class and custom
// properties: without the stylesheet the page is as the app drew it)
static void remove_sheet(void *view) {
    void (*rm_ss)(void *, void *) = sym("webkit_user_content_manager_remove_style_sheet");
    void *ucm = content_manager(view), *ss = obj_get(view, ITEMS[0]);
    if (!ucm || !ss) return;
    if (rm_ss) rm_ss(ucm, ss);
    obj_set(view, ITEMS[0], NULL, NULL);   // drops the ref
    LOG("glass stylesheet removed");
}

// once per view, before its first load: the stylesheet, the page scripts and the focus script
static void inject(void *view) {
    if (dbg()) { // console.log -> stdout of the web process (lands in the app log)
        void *(*get_settings)(void *) = sym("webkit_web_view_get_settings");
        void (*wc)(void *, gboolean) = sym("webkit_settings_set_enable_write_console_messages_to_stdout");
        if (get_settings && wc) wc(get_settings(view), 1);
    }
    void *ucm = content_manager(view);
    if (!ucm) return;
    int had_css = add_sheet(view) && obj_get(view, ITEMS[0]);
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

// the first document committed: the window decided afresh (its views as they are now, not as
// they were at the last map), so a window glassed meanwhile turns app-paintable now
static void first_document(void *view) {
    if (obj_get(view, "appglass-shown")) return;
    obj_set(view, "appglass-shown", (void *)1, NULL);
    void *(*get_toplevel)(void *) = sym("gtk_widget_get_toplevel");
    void *top = get_toplevel ? get_toplevel(view) : NULL;
    if (top) redecide(top);
}
static void on_load_changed(void *view, int ev, void *data) {
    (void)data;
    if (ev >= 2) first_document(view);   // WEBKIT_LOAD_COMMITTED (2), FINISHED (3)
}

static void glassify(void *view) {
    if (obj_get(view, "appglass")) return;
    obj_set(view, "appglass", (void *)1, NULL);
    GdkRGBA clear = { 0, 0, 0, 0 };
    real_set_bg(view, &clear);
    unsigned long (*connect)(void *, const char *, void *, void *, void *, int) = sym("g_signal_connect_data");
    gboolean (*is_loading)(void *) = sym("webkit_web_view_is_loading");
    const char *(*get_uri)(void *) = sym("webkit_web_view_get_uri");
    if (connect) connect(view, "load-changed", (void *)on_load_changed, NULL, NULL, 0);
    // seen at its map (GTK_MODULES) with a page in already; no way to tell: glass at once
    if (!connect || !is_loading || !get_uri || (!is_loading(view) && get_uri(view)))
        obj_set(view, "appglass-shown", (void *)1, NULL);
    inject(view);
    if (!glass_toplevel(view)) {  // not in a window yet (wry builds the view first): when it is
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
