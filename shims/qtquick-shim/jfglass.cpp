// jfglass: LD_PRELOAD shim for Jellyfin Desktop 2.x (Qt Quick + QtWebEngine + mpv).
// Gives the window an alpha channel and keeps the mpv video layer only while a video is open.
//  - before any window exists: QQuickWindow::setDefaultAlphaBuffer(true)
//  - wraps QQmlApplicationEngine::load(QUrl) (PLT call from the app binary); afterwards a 1 s timer:
//      window colour -> transparent, WebEngineView background -> transparent,
//      asks the page whether a video is open (.videoPlayerContainer, created by Jellyfin's own
//      mpvVideoPlayer.js for the whole video session) and (re)injects the CSS file named by JFGLASS_CSS.
//  - MpvVideoItem 'video' (paints opaque black + the video) is visible only while a video is open,
//    and is never hidden before its first frame (mpv's render context is created on that frame).
//  - PlayerComponent state signals trigger an immediate re-check, so the video layer appears at load time.
//  - QQuickWindow activeChanged sets html.agl-inactive on the page while the window is not active
//    (the CSS fades the content background; nothing runs between focus changes).
// Only reads one file (JFGLASS_CSS). No network, no processes, no file writes.
#include <QQuickWindow>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQmlPropertyMap>
#include <QJSEngine>
#include <QJSValue>
#include <QQuickItem>
#include <QTimer>
#include <QFile>
#include <QPointer>
#include <QMetaMethod>
#include <QElapsedTimer>
#include <dlfcn.h>
#include <unistd.h>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>

static bool g_active = false;
#define LOG(...) do { if (g_log) fprintf(stderr, "jfglass: " __VA_ARGS__); } while (0)
static bool g_log = false;
static QString g_css;   // JFGLASS_CSS, read once at load (then unset)

static const char *POLL_JS =
    "(function(){var s=document.getElementById('jfglass');if(!s||!document.head)return -1;"
    "if(s.parentNode!==document.head||s.nextElementSibling)document.head.appendChild(s);"
    "return document.querySelector('.videoPlayerContainer')?1:0;})()";

class JfGlass : public QObject {
    Q_OBJECT
public:
    explicit JfGlass(QQmlApplicationEngine *e) : QObject(e), eng(e) {
        QFile f(g_css);
        if (f.open(QIODevice::ReadOnly)) css = QString::fromUtf8(f.read(256 * 1024));
        LOG("css %lld bytes\n", (long long)css.size());
        up.start();
        connect(&timer, &QTimer::timeout, this, &JfGlass::tick);
        timer.start(1000);
        QTimer::singleShot(0, this, &JfGlass::tick);
    }
public Q_SLOTS:
    void tick() { find(); poll(); }
    void onReady() { LOG("mpv ready\n"); ready = true; apply(); }
    void poll() {
        if (!web) return;
        if (cb.isUndefined()) {
            QJSEngine::setObjectOwnership(this, QJSEngine::CppOwnership);
            cb = eng->evaluate(QStringLiteral("(function(h){return function(r){h.state(r);};})"))
                     .call({eng->newQObject(this)});
        }
        QMetaObject::invokeMethod(web, "runJavaScript", Q_ARG(QString, QString::fromLatin1(POLL_JS)), Q_ARG(QJSValue, cb));
    }
    void state(const QVariant &r) {
        bool ok = false; int v = r.toInt(&ok);
        if (!ok) return;
        if (v < 0) { inject(); return; }
        if ((v == 1) != video_open) { video_open = (v == 1); LOG("video open=%d\n", video_open); apply(); }
    }
private:
    void find() {
        if (!win) for (QObject *r : eng->rootObjects()) if (auto *w = qobject_cast<QQuickWindow *>(r)) { win = w; break; }
        if (!win) return;
        if (win->color().alpha() != 0) { LOG("window colour -> transparent\n"); win->setColor(Qt::transparent); }
        if (!focusHooked) { focusHooked = true; connect(win, &QWindow::activeChanged, this, &JfGlass::focus); }
        if (!video) {
            video = win->findChild<QQuickItem *>(QStringLiteral("video"));
            if (video) connect(video, SIGNAL(ready()), this, SLOT(onReady()));
        }
        if (!web) {
            web = win->findChild<QObject *>(QStringLiteral("web"));
            if (web) web->setProperty("backgroundColor", QColor(Qt::transparent));
        }
        if (!player) {
            QObject *m = eng->rootContext()->contextProperty(QStringLiteral("components")).value<QObject *>();
            if (auto *map = qobject_cast<QQmlPropertyMap *>(m)) player = map->value(QStringLiteral("player")).value<QObject *>();
            if (player) {
                const QMetaObject *mo = player->metaObject();
                QMetaMethod slot = metaObject()->method(metaObject()->indexOfSlot("poll()"));
                for (int i = 0; i < mo->methodCount(); i++) {
                    QMetaMethod s = mo->method(i);
                    if (s.methodType() != QMetaMethod::Signal) continue;
                    QByteArray n = s.name();
                    if (n == "stateChanged" || n == "playing" || n == "stopped" || n == "onVideoRecangleChanged") connect(player, s, this, slot);
                }
                LOG("player hooked\n");
            }
        }
        // first frame never seen (signal missed)? after 15 s mpv has certainly rendered once
        if (!ready && video && up.elapsed() > 15000) { LOG("ready by timeout\n"); ready = true; }
        apply();
    }
    void apply() {
        if (!video) return;
        bool show = video_open || !ready;
        if (video->isVisible() != show) { LOG("video layer visible=%d\n", show); video->setVisible(show); }
    }
    void inject() {
        if (!web || css.isEmpty()) return;
        QString c = css;
        c.replace(QLatin1String("\\"), QLatin1String("\\\\")).replace(QLatin1String("'"), QLatin1String("\\'"))
         .replace(QLatin1String("\n"), QLatin1String("\\n")).replace(QLatin1String("\r"), QString())
         .replace(QLatin1String("<"), QLatin1String("\\x3c"));
        QString js = QStringLiteral("(function(){if(!document.head)return;var s=document.getElementById('jfglass');"
                                    "if(!s){s=document.createElement('style');s.id='jfglass';}s.textContent='%1';"
                                    "document.head.appendChild(s);})()").arg(c);
        QMetaObject::invokeMethod(web, "runJavaScript", Q_ARG(QString, js));
        LOG("css injected\n");
        focus();   // a new page: put the focus class back
    }
    // unfocused fade: html.agl-inactive while the window is not active; the CSS transition eases it
    void focus() {
        if (!web || !win) return;
        QString js = QStringLiteral("document.documentElement&&document.documentElement.classList.toggle('agl-inactive',%1)")
                         .arg(win->isActive() ? QLatin1String("false") : QLatin1String("true"));
        QMetaObject::invokeMethod(web, "runJavaScript", Q_ARG(QString, js));
        LOG("window active=%d\n", win->isActive());
    }
    QQmlApplicationEngine *eng;
    QString css;
    QTimer timer;
    QElapsedTimer up;
    QPointer<QQuickWindow> win;
    QPointer<QQuickItem> video;
    QPointer<QObject> web, player;
    QJSValue cb;
    bool ready = false, video_open = false, focusHooked = false;
};


static void (*real_load)(QQmlApplicationEngine *, const QUrl &);
extern "C" void _ZN21QQmlApplicationEngine4loadERK4QUrl(QQmlApplicationEngine *self, const QUrl &url) {
    if (!real_load) real_load = reinterpret_cast<decltype(real_load)>(dlsym(RTLD_NEXT, "_ZN21QQmlApplicationEngine4loadERK4QUrl"));
    real_load(self, url);
    if (!g_active || self->findChild<JfGlass *>()) return;
    LOG("load %s\n", qPrintable(url.toString()));
    auto *g = new JfGlass(self);
    g->tick();   // hook mpv's first-frame signal now, before the event loop renders anything
}

__attribute__((constructor)) static void jfglass_init() {
    char exe[PATH_MAX]; ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0) return;
    exe[n] = 0;
    const char *b = strrchr(exe, '/'); b = b ? b + 1 : exe;
    const bool app = strcmp(b, "jellyfin-desktop") == 0;
    // a launcher shell between flatpak and the app passes the preload on; any other process it
    // reaches (QtWebEngineProcess, a helper the command starts instead) drops it and does nothing
    static const char *const chain[] = {"sh", "bash", "dash", "env"};
    if (!app)
        for (const char *c : chain)
            if (strcmp(b, c) == 0) return;
    if (app) {
        g_log = qEnvironmentVariableIsSet("JFGLASS_LOG");
        g_css = qEnvironmentVariable("JFGLASS_CSS");
    }
    unsetenv("LD_PRELOAD");                              // children do not inherit the shim
    unsetenv("JFGLASS_CSS");
    unsetenv("JFGLASS_LOG");
    if (!app) return;
    g_active = true;
    QQuickWindow::setDefaultAlphaBuffer(true);
    LOG("preload active\n");
}

#include "jfglass.moc"
