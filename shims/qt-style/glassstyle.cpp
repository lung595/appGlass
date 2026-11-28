// appGlass QStyle plugin: QProxyStyle over Fusion that gives Qt Widgets apps three glass levels.
//   content (window bg, item views)          : DMS surface_container at APPGLASS_CONTENT (0.60)
//   bars (menubar, toolbar, statusbar, tabbar,
//         header, dock title) painted OVER it : same colour at APPGLASS_BAR (0.125) -> ~0.65 effective
//   menus, combo popups, tooltips, dialogs    : opaque (APPGLASS_DIALOGS=glass makes dialogs glass too)
//   text roles                                : always opaque
// Load: QT_PLUGIN_PATH=<dir containing styles/> QT_STYLE_OVERRIDE=appglass
// Colours: APPGLASS_COLORS (default ~/.cache/dms/dms-colors.json, "mode" picks dark/light).
// Environment: the style reads its variables once (env()) and takes them out of the process
// environment (APPGLASS_*, QT_STYLE_OVERRIDE=appglass, its own QT_PLUGIN_PATH entry), so a
// shell, a game or any app the Qt app starts never inherits them. Qt has read
// QT_STYLE_OVERRIDE and QT_PLUGIN_PATH before it creates the style. An appglass dir in
// XDG_CONFIG_DIRS (Kate's glass katerc) is taken out once the event loop runs.
// Opaque-paint widgets (WA_OpaquePaintEvent: KTextEditor's view and icon border) in a glass
// window lose the attribute, so the glass under them is painted (no holes, no double fill).
#include <QtWidgets>
#include <QStylePlugin>
#include <dlfcn.h>
#include <unistd.h>
#include <cstring>
extern char **environ;

namespace {
struct Env { QString colors; double content, bar;
             bool dialogs, debug, debug2; QStringList opaque; };

double envF(const char *n, double d) { bool ok; double v = qEnvironmentVariable(n).toDouble(&ok); return ok ? v : d; }

// take the style's variables out of the environment (children never inherit them):
// every APPGLASS_*, QT_STYLE_OVERRIDE=appglass and the plugin dir this library was loaded from
void scrubEnv() {
    QList<QByteArray> names;
    for (char **e = environ; e && *e; e++)
        if (!strncmp(*e, "APPGLASS_", 9)) names << QByteArray(*e, int(strcspn(*e, "=")));
    for (const QByteArray &n : names) qunsetenv(n.constData());
    if (qEnvironmentVariable("QT_STYLE_OVERRIDE").compare("appglass", Qt::CaseInsensitive) == 0)
        qunsetenv("QT_STYLE_OVERRIDE");
    QString mine;   // <dir>/styles/libappglass.so -> <dir>
    Dl_info info;
    if (dladdr(reinterpret_cast<void *>(&scrubEnv), &info) && info.dli_fname)
        mine = QFileInfo(QString::fromLocal8Bit(info.dli_fname)).canonicalPath() + "/..";
    mine = QDir(mine).canonicalPath();
    if (qEnvironmentVariableIsSet("QT_PLUGIN_PATH")) {
        QStringList keep;
        for (const QString &d : qEnvironmentVariable("QT_PLUGIN_PATH").split(':', Qt::SkipEmptyParts)) {
            const QString c = QDir(d).canonicalPath();
            if (!(c.isEmpty() ? QDir::cleanPath(d) : c).endsWith("/appglass/qt6") && (mine.isEmpty() || c != mine))
                keep << d;
        }
        if (keep.isEmpty()) qunsetenv("QT_PLUGIN_PATH");
        else qputenv("QT_PLUGIN_PATH", keep.join(':').toLocal8Bit());
    }
}

// the Kate launcher's glass katerc dir (<...>/appglass) in front of XDG_CONFIG_DIRS: KConfig reads
// the cascade while the app starts, so it leaves only once the event loop runs (before any child)
void scrubXdg() {
    if (!qEnvironmentVariableIsSet("XDG_CONFIG_DIRS")) return;
    QStringList keep;
    for (const QString &d : qEnvironmentVariable("XDG_CONFIG_DIRS").split(':', Qt::SkipEmptyParts))
        if (!QDir::cleanPath(d).endsWith("/appglass")) keep << d;
    if (keep.isEmpty()) qunsetenv("XDG_CONFIG_DIRS");
    else qputenv("XDG_CONFIG_DIRS", keep.join(':').toLocal8Bit());
}

// one hop only: the levels are kept here, the variables leave the environment
const Env &env() {
    static const Env e = [] {
        Env v{qEnvironmentVariable("APPGLASS_COLORS", QDir::homePath() + "/.cache/dms/dms-colors.json"),
              envF("APPGLASS_CONTENT", 0.60), envF("APPGLASS_BAR", 0.125),
              qEnvironmentVariable("APPGLASS_DIALOGS") == "glass", qEnvironmentVariableIsSet("APPGLASS_DEBUG"),
              qEnvironmentVariable("APPGLASS_DEBUG") == "2",
              qEnvironmentVariable("APPGLASS_OPAQUE").split(',', Qt::SkipEmptyParts)};
        scrubEnv();
        return v;
    }();
    return e;
}

struct Pal { QColor win, high, highest, fg, fgVar, outline, hl, onHl, link; };

Pal loadPal() {
    Pal p{QColor("#1e2226"), QColor("#282c30"), QColor("#33373b"), QColor("#e0e2e8"), QColor("#c2c7cf"),
          QColor("#8c9198"), QColor("#9acbfa"), QColor("#003150"), QColor("#9acbfa")};
    QFile f(env().colors);
    if (!f.open(QIODevice::ReadOnly)) return p;
    auto root = QJsonDocument::fromJson(f.readAll()).object();
    QString mode = root.value("mode").toString("dark");
    auto c = root.value("colors").toObject().value(mode).toObject();
    auto g = [&](const char *k, QColor &dst) { auto v = c.value(k).toString(); if (!v.isEmpty()) dst = QColor(v); };
    g("surface_container", p.win); g("surface_container_high", p.high); g("surface_container_highest", p.highest);
    g("on_surface", p.fg); g("on_surface_variant", p.fgVar); g("outline", p.outline);
    g("primary", p.hl); g("on_primary", p.onHl); g("primary", p.link);
    return p;
}
QColor withA(QColor c, double a) { c.setAlphaF(a); return c; }
bool isBar(const QWidget *w) {
    return qobject_cast<const QMenuBar *>(w) || qobject_cast<const QToolBar *>(w) || qobject_cast<const QStatusBar *>(w)
        || qobject_cast<const QTabBar *>(w) || qobject_cast<const QHeaderView *>(w);
}
bool isPopup(const QWidget *w) {
    if (!w->isWindow()) return false;
    auto t = w->windowType();
    return t == Qt::Popup || t == Qt::ToolTip || qobject_cast<const QMenu *>(w)
        || w->inherits("QTipLabel") || w->inherits("QComboBoxPrivateContainer");
}
}

class GlassStyle : public QProxyStyle {
public:
    GlassStyle() : QProxyStyle(QStyleFactory::create("Fusion")), pal(loadPal()) {
        content = env().content;
        bar = env().bar;
        glassDialogs = env().dialogs;
        dbg2 = env().debug2; if (dbg2) qApp->installEventFilter(this);
        opaqueApps = env().opaque;
        QTimer::singleShot(0, qApp, scrubXdg);
    }
    // opaque base palette (popups, dialogs) - text roles always opaque
    QPalette opaquePalette() const {
        QPalette p = baseStyle()->standardPalette();
        auto all = [&](QPalette::ColorRole r, QColor c) { p.setColor(QPalette::All, r, c); };
        all(QPalette::Window, pal.high); all(QPalette::Base, pal.win); all(QPalette::AlternateBase, pal.high);
        all(QPalette::Button, pal.highest); all(QPalette::ToolTipBase, pal.high);
        for (auto r : {QPalette::WindowText, QPalette::Text, QPalette::ButtonText, QPalette::ToolTipText, QPalette::BrightText})
            all(r, pal.fg);
        all(QPalette::PlaceholderText, pal.fgVar);
        all(QPalette::Highlight, pal.hl); all(QPalette::HighlightedText, pal.onHl);
        all(QPalette::Link, pal.link); all(QPalette::LinkVisited, pal.link);
        all(QPalette::Light, pal.highest.lighter(130)); all(QPalette::Midlight, pal.highest);
        all(QPalette::Mid, pal.outline); all(QPalette::Dark, pal.win.darker(150)); all(QPalette::Shadow, Qt::black);
        for (auto r : {QPalette::WindowText, QPalette::Text, QPalette::ButtonText})
            p.setColor(QPalette::Disabled, r, pal.outline);
        return p;
    }
    // glass palette: Window is fully transparent here, because the window background is painted
    // once by the event filter (content level). Children that fill with Window/Base add nothing.
    QPalette glassPalette() const {
        QPalette p = opaquePalette();
        auto all = [&](QPalette::ColorRole r, QColor c) { p.setColor(QPalette::All, r, c); };
        all(QPalette::Window, Qt::transparent); all(QPalette::Base, Qt::transparent);
        all(QPalette::AlternateBase, withA(pal.fg, 0.04));
        all(QPalette::Button, withA(pal.highest, 0.55));
        return p;
    }
    QPalette standardPalette() const override { return opaquePalette(); }
    void polish(QPalette &p) override { p = opaquePalette(); }
    void polish(QWidget *w) override {
        QProxyStyle::polish(w);
        if (env().debug && (w->autoFillBackground() || w->isWindow()))
            qWarning("appglass polish %s '%s' autofill=%d role=%d parent=%s", w->metaObject()->className(),
                     qPrintable(w->objectName()), w->autoFillBackground(), int(w->backgroundRole()),
                     w->parentWidget() ? w->parentWidget()->metaObject()->className() : "-");
        if (isPopup(w)) { w->setPalette(opaquePalette()); return; }
        if (!w->isWindow() && w->testAttribute(Qt::WA_OpaquePaintEvent) && !isPopup(w->window())
            && !w->testAttribute(Qt::WA_NativeWindow) && !w->testAttribute(Qt::WA_PaintOnScreen)
            && !w->inherits("QOpenGLWidget") && !w->inherits("QQuickWidget"))
            w->setAttribute(Qt::WA_OpaquePaintEvent, false);   // the glass under it gets painted
        if (w->isWindow()) {
            bool dialog = qobject_cast<QDialog *>(w) || w->windowType() == Qt::Dialog || w->windowType() == Qt::Sheet;
            bool skip = opaqueApps.contains(QCoreApplication::applicationName(), Qt::CaseInsensitive)
                     || (dialog && !glassDialogs) || w->windowType() == Qt::Desktop
                     || !(w->windowType() == Qt::Window || w->windowType() == Qt::Dialog);
            if (skip) { w->setPalette(opaquePalette()); return; }
            bool late = w->testAttribute(Qt::WA_WState_Created) && !w->testAttribute(Qt::WA_TranslucentBackground);
            w->setAttribute(Qt::WA_TranslucentBackground);
            // QWidget::create() runs before polish(), so the platform window usually exists already
            // with an opaque format. If it is not visible yet, drop the platform window: show()
            // recreates it with the alpha format requested by WA_TranslucentBackground.
            if (late && !w->isVisible()) if (QWindow *wh = w->windowHandle()) {
                QSurfaceFormat f = wh->format(); f.setAlphaBufferSize(8); wh->setFormat(f);
                if (wh->handle()) wh->destroy();
            }
            w->setPalette(glassPalette());
            w->setProperty("appglass_f", true); w->installEventFilter(this);
            return;
        }
        if (isBar(w)) {
            // bars: filled once at the bar level in the filter; their own Button/Window fills
            // (QHeaderView viewport autofill, Fusion tab gradients) would stack on top -> clear them
            QPalette p = w->palette(); p.setColor(QPalette::Button, Qt::transparent); p.setColor(QPalette::Window, Qt::transparent);
            w->setPalette(p);
            w->setProperty("appglass_f", true); w->installEventFilter(this);
        } else if (qobject_cast<QLineEdit *>(w) || qobject_cast<QAbstractSpinBox *>(w) || qobject_cast<QCheckBox *>(w) || qobject_cast<QRadioButton *>(w)) {
            QPalette p = w->palette(); p.setColor(QPalette::Base, withA(pal.highest, 0.5)); w->setPalette(p);
        } else if (auto *dw = qobject_cast<QDockWidget *>(w)) {
            dw->setProperty("appglass_f", true); w->installEventFilter(this);
        }
    }
    void unpolish(QWidget *w) override { w->removeEventFilter(this); QProxyStyle::unpolish(w); }

    bool eventFilter(QObject *o, QEvent *e) override {
        if (e->type() == QEvent::Paint && dbg2 && o->isWidgetType()) {
            auto *w = static_cast<QWidget *>(o);
            if (w->width() > 400 && w->height() > 300 && !seen.contains(w)) { seen.insert(w);
                QBrush b = w->palette().brush(w->backgroundRole());
                qWarning("appglass paint %s '%s' %dx%d autofill=%d role=%d bgA=%d btnA=%d ss=%d", w->metaObject()->className(), qPrintable(w->objectName()),
                         w->width(), w->height(), w->autoFillBackground(), int(w->backgroundRole()), b.color().alpha(),
                         w->palette().button().color().alpha(), !w->styleSheet().isEmpty());
                qWarning("   bg=%s appBase=%s", qPrintable(b.color().name(QColor::HexArgb)), qPrintable(qApp->palette().base().color().name(QColor::HexArgb))); }
        }
        if (e->type() == QEvent::Paint && o->property("appglass_f").toBool()) {
            auto *w = static_cast<QWidget *>(o);
            QPainter p(w);
            QColor c;
            QRect r = w->rect();
            if (w->isWindow() && w->testAttribute(Qt::WA_TranslucentBackground)) {
                c = withA(pal.win, content);
                p.setCompositionMode(QPainter::CompositionMode_Source);  // define the alpha exactly once
                p.fillRect(static_cast<QPaintEvent *>(e)->rect(), c);
                return false;
            }
            // QDockWidget: the whole dock is a sidebar -> bar level, like the QML sidebar
            p.fillRect(r, withA(pal.win, bar));
        }
        return false;
    }
    // Fusion paints these with Window/Button on top of our bar fill; keep their own fill out
    void drawControl(ControlElement el, const QStyleOption *opt, QPainter *p, const QWidget *w) const override {
        if (el == CE_MenuBarEmptyArea || el == CE_ToolBar) return;
        if (el == CE_HeaderEmptyArea) return;
        if (el == CE_DockWidgetTitle) {
            if (auto *d = qstyleoption_cast<const QStyleOptionDockWidget *>(opt)) {
                QStyleOptionDockWidget o = *d; o.palette.setColor(QPalette::Window, Qt::transparent);
                o.palette.setColor(QPalette::Button, Qt::transparent);
                return QProxyStyle::drawControl(el, &o, p, w);
            }
        }
        if (el == CE_HeaderSection) {
            // flat section, the bar tint comes from the filter
            p->save(); p->setPen(withA(pal.outline, 0.35));
            p->drawLine(opt->rect.topRight(), opt->rect.bottomRight());
            p->drawLine(opt->rect.bottomLeft(), opt->rect.bottomRight()); p->restore();
            return;
        }
        QProxyStyle::drawControl(el, opt, p, w);
    }
    void drawPrimitive(PrimitiveElement pe, const QStyleOption *opt, QPainter *p, const QWidget *w) const override {
        if (pe == PE_PanelMenuBar || pe == PE_PanelToolBar || pe == PE_PanelStatusBar) return;
        if (pe == PE_FrameTabBarBase) return;
        if (pe == PE_FrameTabWidget) {
            // Fusion fills the tab pane with Button (0.55) -> stacks to ~0.82; draw an outline only
            p->save(); p->setPen(withA(pal.outline, 0.35)); p->setBrush(Qt::NoBrush);
            p->drawRect(opt->rect.adjusted(0, 0, -1, -1)); p->restore(); return;
        }
        QProxyStyle::drawPrimitive(pe, opt, p, w);
    }
private:
    Pal pal; double content, bar; bool glassDialogs; QStringList opaqueApps; bool dbg2 = false; mutable QSet<QObject*> seen;
};

class GlassStylePlugin : public QStylePlugin {
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QStyleFactoryInterface_iid FILE "appglass.json")
public:
    QStyle *create(const QString &key) override {
        return key.compare("appglass", Qt::CaseInsensitive) == 0 ? new GlassStyle : nullptr;
    }
};
#include "glassstyle.moc"
