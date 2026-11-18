// fakegtk: the few GTK3 / GObject / WebKitGTK calls appglass-wk.so makes, on a
// toy widget tree, so its window decision runs without a display
// (tests/test_webkit.py ShimDecision). Build as a library (fakegtk.so) and
// link a driver against it; the shim is preloaded and finds these by dlsym.
//
// Driver API: fk_widget(name, parent, toplevel) makes a widget (visible),
// fk_show/fk_hide set visible and map/unmap it when its parent is mapped,
// fk_map maps a toplevel and its visible children, fk_frame gives a widget a
// border-width and margins, fk_titlebar makes a child of a window its custom
// titlebar (gtk_container_get_children lists it, as GTK3's forall does; a
// widget named "headerbar..." is a GtkHeaderBar), fk_idle runs the queued
// idles, then finishes the page loads asked for (a document runs the user
// scripts registered when it finishes loading, as WebKit's do at document
// end, and the view emits load-changed committed then finished: fk_navigate
// starts another document; fk_hold keeps a view's loads from finishing until
// released, fk_commit commits a held load without finishing it), fk_report
// prints one line of the window and the view.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { double r, g, b, a; } GdkRGBA;
typedef struct L { void *data; struct L *next, *prev; } L;
typedef struct D { const char *k; void *v; void (*destroy)(void *); struct D *next; } D;
typedef struct H { const char *sig; void *fn; void *data; int flags; struct H *next; } H;
typedef struct W {
    const char *name; struct W *parent, *kids[8]; int nkids;
    int top, visible, mapped, realized, paintable, draws, refs;
    unsigned border; int margin;         // container border-width; the same margin on each side
    struct W *titlebar;                  // a window: its custom titlebar
    D *data; H *handlers;
    GdkRGBA bg; int sheets, scripts;     // a WebView: its background, its content manager
    int loading, page, shown, held, committed;   // ... a document loading; the scripts its document
                                         //     ran; a document committed once; its loads held; the
                                         //     load in progress committed
} W;
static W *loads[16]; static int nloads;
static void load(W *v) { v->loading = 1; v->committed = 0; if (nloads < 16) loads[nloads++] = v; }
static void load_changed(W *v, int ev) {
    for (H *h = v->handlers; h; h = h->next)
        if (!strcmp(h->sig, "load-changed")) ((void (*)(void *, int, void *))h->fn)(v, ev, h->data);
}

static W ucm_dummy;
static void *visual_dummy = &ucm_dummy, *screen_dummy = &ucm_dummy;

// ------------------------------------------------------------------ gobject
void *g_object_get_data(void *o, const char *k) {
    for (D *d = ((W *)o)->data; d; d = d->next) if (!strcmp(d->k, k)) return d->v;
    return NULL;
}
void g_object_set_data_full(void *o, const char *k, void *v, void (*destroy)(void *)) {
    W *w = o;
    for (D **p = &w->data; *p; p = &(*p)->next) if (!strcmp((*p)->k, k)) {
        D *d = *p; *p = d->next;
        if (d->destroy && d->v) d->destroy(d->v);
        free(d); break;
    }
    if (!v) return;
    D *d = calloc(1, sizeof *d); d->k = strdup(k); d->v = v; d->destroy = destroy;
    d->next = w->data; w->data = d;
}
void *g_object_ref(void *o) { ((W *)o)->refs++; return o; }
void g_object_unref(void *o) { ((W *)o)->refs--; }
void g_list_free(void *l) { while (l) { L *n = ((L *)l)->next; free(l); l = n; } }

typedef struct { void **p; } WeakRef;
void g_weak_ref_init(void *wr, void *o) { ((WeakRef *)wr)->p = o; }
void *g_weak_ref_get(void *wr) { void *o = ((WeakRef *)wr)->p; return o ? g_object_ref(o) : NULL; }
void g_weak_ref_clear(void *wr) { ((WeakRef *)wr)->p = NULL; }

typedef struct { int (*fn)(void *); void *data; void (*destroy)(void *); } Idle;
static Idle idles[256]; static int nidle;
unsigned g_idle_add_full(int prio, int (*fn)(void *), void *data, void (*destroy)(void *)) {
    (void)prio; idles[nidle].fn = fn; idles[nidle].data = data; idles[nidle].destroy = destroy;
    return ++nidle;
}
void fk_idle(void) {
    for (int round = 0; round < 8 && nidle; round++) {
        Idle q[256]; int n = nidle; memcpy(q, idles, sizeof q); nidle = 0;
        for (int i = 0; i < n; i++) { q[i].fn(q[i].data); if (q[i].destroy) q[i].destroy(q[i].data); }
    }
    int kept = 0;
    for (int i = 0; i < nloads; i++) {
        W *v = loads[i];
        if (v->held) { loads[kept++] = v; continue; }
        if (!v->loading) continue;
        v->loading = 0; v->page = v->scripts; v->shown = 1;
        if (!v->committed) load_changed(v, 2);   // WEBKIT_LOAD_COMMITTED
        v->committed = 0;
        load_changed(v, 3);                      // WEBKIT_LOAD_FINISHED
    }
    nloads = kept;
}

static void add_handler(W *w, const char *sig, void *fn, void *data, int flags) {
    H *h = calloc(1, sizeof *h); h->sig = strdup(sig); h->fn = fn; h->data = data; h->flags = flags;
    h->next = w->handlers; w->handlers = h;
}
unsigned long g_signal_connect_object(void *o, const char *sig, void *fn, void *gobj, int flags) {
    add_handler(o, sig, fn, gobj, flags); return 1;
}
unsigned long g_signal_connect_data(void *o, const char *sig, void *fn, void *data, void *dn, int flags) {
    (void)dn; add_handler(o, sig, fn, data, flags); return 1;
}
// emission hooks: map (1) and unmap (2)
typedef int (*Hook)(void *, unsigned, const void *, void *);
static struct { unsigned sig; Hook fn; void *data; } hooks[8]; static int nhooks;
unsigned long gtk_widget_get_type(void) { return 42; }
void *g_type_class_ref(unsigned long t) { (void)t; return &ucm_dummy; }
unsigned g_signal_lookup(const char *name, unsigned long t) {
    (void)t; return !strcmp(name, "map") ? 1 : !strcmp(name, "unmap") ? 2 : 0;
}
unsigned long g_signal_add_emission_hook(unsigned sig, unsigned detail, void *fn, void *data, void *dn) {
    (void)detail; (void)dn; hooks[nhooks].sig = sig; hooks[nhooks].fn = (Hook)fn; hooks[nhooks].data = data;
    return ++nhooks;
}
void *g_value_get_object(const void *v) { return *(void *const *)v; }
static void emit(W *w, const char *sig) {
    unsigned id = !strcmp(sig, "map") ? 1 : 2;
    void *val[3] = { w, 0, 0 };          // a GValue holding the instance (params[0])
    for (int i = 0; i < nhooks; i++) if (hooks[i].sig == id) hooks[i].fn(NULL, 1, val, hooks[i].data);
    for (int after = 0; after < 2; after++)
        for (H *h = w->handlers; h; h = h->next) if (!strcmp(h->sig, sig) && !!(h->flags & 1) == after) {
            if (h->flags & 2) ((void (*)(void *, void *))h->fn)(h->data, w);
            else ((void (*)(void *, void *))h->fn)(w, h->data);
        }
}

// ---------------------------------------------------------------------- gtk
void *gtk_widget_get_parent(void *w) { return ((W *)w)->parent; }
int gtk_widget_get_mapped(void *w) { return ((W *)w)->mapped; }
unsigned gtk_container_get_border_width(void *w) { return ((W *)w)->border; }
int gtk_widget_get_margin_start(void *w) { return ((W *)w)->margin; }
int gtk_widget_get_margin_end(void *w) { return ((W *)w)->margin; }
int gtk_widget_get_margin_top(void *w) { return ((W *)w)->margin; }
int gtk_widget_get_margin_bottom(void *w) { return ((W *)w)->margin; }
const char *gtk_widget_get_name(void *w) { return ((W *)w)->name; }
void *gtk_window_get_titlebar(void *w) { return ((W *)w)->titlebar; }
unsigned long gtk_header_bar_get_type(void) { return 77; }
int g_type_check_instance_is_a(void *w, unsigned long t) {
    return t == 77 && !strncmp(((W *)w)->name, "headerbar", 9);
}
void *gtk_container_get_children(void *c) {
    W *w = c; L *head = NULL, *tail = NULL;
    for (int i = 0; i < w->nkids; i++) {
        L *n = calloc(1, sizeof *n); n->data = w->kids[i]; n->prev = tail;
        if (tail) tail->next = n; else head = n;
        tail = n;
    }
    return head;
}
void *gtk_widget_get_toplevel(void *w) { W *t = w; while (t->parent) t = t->parent; return t; }
int gtk_widget_is_toplevel(void *w) { return ((W *)w)->top; }
int gtk_widget_get_realized(void *w) { return ((W *)w)->realized; }
void *gtk_widget_get_screen(void *w) { (void)w; return screen_dummy; }
void *gdk_screen_get_rgba_visual(void *s) { (void)s; return visual_dummy; }
void gtk_widget_set_visual(void *w, void *v) { (void)w; (void)v; }
void gtk_widget_set_app_paintable(void *w, int on) { ((W *)w)->paintable = on; }
void gtk_widget_queue_draw(void *w) { ((W *)w)->draws++; }

// ------------------------------------------------------------------- webkit
void webkit_web_view_set_background_color(void *v, const GdkRGBA *c) { ((W *)v)->bg = *c; }
void webkit_web_view_load_html(void *v, const char *html, const char *base) { (void)html; (void)base; load(v); }
int webkit_web_view_is_loading(void *v) { return ((W *)v)->loading; }
const char *webkit_web_view_get_uri(void *v) { return ((W *)v)->shown || ((W *)v)->loading ? "about:blank" : NULL; }
void *webkit_web_view_get_user_content_manager(void *v) { return v; }   // the view counts its items
void *webkit_web_view_get_settings(void *v) { return v; }
void webkit_settings_set_enable_write_console_messages_to_stdout(void *s, int on) { (void)s; (void)on; }
static int item;
void *webkit_user_style_sheet_new(const char *s, int a, int b, const char *const *c, const char *const *d) {
    (void)s; (void)a; (void)b; (void)c; (void)d; return &item;
}
void *webkit_user_script_new(const char *s, int a, int b, const char *const *c, const char *const *d) {
    (void)s; (void)a; (void)b; (void)c; (void)d; return &item;
}
void webkit_user_style_sheet_unref(void *s) { (void)s; }
void webkit_user_script_unref(void *s) { (void)s; }
void webkit_user_content_manager_add_style_sheet(void *m, void *s) { (void)s; ((W *)m)->sheets++; }
void webkit_user_content_manager_remove_style_sheet(void *m, void *s) { (void)s; ((W *)m)->sheets--; }
void webkit_user_content_manager_add_script(void *m, void *s) { (void)s; ((W *)m)->scripts++; }
void webkit_user_content_manager_remove_script(void *m, void *s) { (void)s; ((W *)m)->scripts--; }

// ------------------------------------------------------------------- driver
void *fk_widget(const char *name, void *parent, int top) {
    W *w = calloc(1, sizeof *w); w->name = name; w->top = top; w->visible = 1;
    w->bg = (GdkRGBA){ 1, 1, 1, 1 };
    if (parent) { W *p = parent; w->parent = p; p->kids[p->nkids++] = w; }
    return w;
}
static void map_tree(W *w) {
    w->mapped = 1;
    for (int i = 0; i < w->nkids; i++) if (w->kids[i]->visible) map_tree(w->kids[i]);
    emit(w, "map");
}
static void unmap_tree(W *w) {
    for (int i = 0; i < w->nkids; i++) if (w->kids[i]->mapped) unmap_tree(w->kids[i]);
    w->mapped = 0;
    emit(w, "unmap");
}
void fk_map(void *top) { ((W *)top)->realized = 1; map_tree(top); }
void fk_show(void *w) { W *x = w; x->visible = 1; if (x->parent && x->parent->mapped) map_tree(x); }
void fk_hide(void *w) { W *x = w; x->visible = 0; if (x->mapped) unmap_tree(x); }
void fk_navigate(void *view) { load(view); }   // the page goes to another document
void fk_hold(void *v, int on) { ((W *)v)->held = on; }
void fk_commit(void *v) { W *x = v; if (x->loading && !x->committed) { x->committed = 1; load_changed(x, 2); } }
void fk_titlebar(void *win, void *w) { ((W *)win)->titlebar = w; }
void fk_frame(void *w, unsigned border, int margin) { ((W *)w)->border = border; ((W *)w)->margin = margin; }
void fk_report(const char *step, void *top, void *view) {
    W *t = top, *v = view;
    printf("%s paintable=%d bg_alpha=%g sheets=%d scripts=%d page=%d\n", step, t->paintable, v->bg.a,
           v->sheets, v->scripts, v->page);
}
