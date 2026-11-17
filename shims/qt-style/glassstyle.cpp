// appGlass QStyle plugin: QProxyStyle over Fusion that gives Qt Widgets apps three glass levels.
//   content (window bg, item views)          : DMS surface_container at APPGLASS_CONTENT (0.60)
//   bars (menubar, toolbar, statusbar, tabbar,
//         header, dock title) painted OVER it : same colour at APPGLASS_BAR (0.125) -> ~0.65 effective
//   menus, combo popups, tooltips, dialogs    : opaque (APPGLASS_DIALOGS=glass makes dialogs glass too)
//   text roles                                : always opaque
//   unfocused top-level window                : content eases to APPGLASS_INACTIVE in APPGLASS_FADE_MS
//                                               (APPGLASS_FADE_EASING: ease-out-cubic, ease-in-out, linear);
//                                               a QVariantAnimation per window, stopped between focus changes
// Load: QT_PLUGIN_PATH=<dir containing styles/> QT_STYLE_OVERRIDE=appglass
// Colours: APPGLASS_COLORS (default ~/.cache/dms/dms-colors.json, "mode" picks dark/light).
#include <QtWidgets>
#include <QStylePlugin>

namespace {
struct Pal { QColor win, high, highest, fg, fgVar, outline, hl, onHl, link; };

Pal loadPal() {
    Pal p{QColor("#1e2226"), QColor("#282c30"), QColor("#33373b"), QColor("#e0e2e8"), QColor("#c2c7cf"),
          QColor("#8c9198"), QColor("#9acbfa"), QColor("#003150"), QColor("#9acbfa")};
    QString path = qEnvironmentVariable("APPGLASS_COLORS", QDir::homePath() + "/.cache/dms/dms-colors.json");
    QFile f(path);
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
double envF(const char *n, double d) { bool ok; double v = qEnvironmentVariable(n).toDouble(&ok); return ok ? v : d; }

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
        content = envF("APPGLASS_CONTENT", 0.60);
        bar = envF("APPGLASS_BAR", 0.125);
        inactive = envF("APPGLASS_INACTIVE", content);
        fadeMs = int(envF("APPGLASS_FADE_MS", 0));
        QString e = qEnvironmentVariable("APPGLASS_FADE_EASING");
        curve = e == "linear" ? QEasingCurve::Linear : e == "ease-in-out" ? QEasingCurve::InOutCubic : QEasingCurve::OutCubic;
        glassDialogs = qEnvironmentVariable("APPGLASS_DIALOGS") == "glass";
        dbg2 = qEnvironmentVariable("APPGLASS_DEBUG") == "2"; if (dbg2) qApp->installEventFilter(this);
        opaqueApps = qEnvironmentVariable("APPGLASS_OPAQUE").split(',', Qt::SkipEmptyParts);
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
        if (qEnvironmentVariableIsSet("APPGLASS_DEBUG") && (w->autoFillBackground() || w->isWindow()))
            qWarning("appglass polish %s '%s' autofill=%d role=%d parent=%s", w->metaObject()->className(),
                     qPrintable(w->objectName()), w->autoFillBackground(), int(w->backgroundRole()),
                     w->parentWidget() ? w->parentWidget()->metaObject()->className() : "-");
        if (isPopup(w)) { w->setPalette(opaquePalette()); return; }
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

    // the window's content level now: the running fade, else its focus state
    double level(const QWidget *w) const {
        QVariant v = w->property("appglass_a");
        return v.isValid() ? v.toDouble() : (w->isActiveWindow() ? content : inactive);
    }
    void fade(QWidget *w, bool active) {
        double from = level(w), to = active ? content : inactive;
        auto *a = w->findChild<QVariantAnimation *>("appglass_fade", Qt::FindDirectChildrenOnly);
        if (a) a->stop();
        if (fadeMs <= 0 || qFuzzyCompare(from, to)) { w->setProperty("appglass_a", to); w->update(); return; }
        if (!a) {
            a = new QVariantAnimation(w); a->setObjectName("appglass_fade");
            QObject::connect(a, &QVariantAnimation::valueChanged, w,
                             [w](const QVariant &v) { w->setProperty("appglass_a", v); w->update(); });
        }
        a->setStartValue(from); a->setEndValue(to); a->setDuration(fadeMs); a->setEasingCurve(curve);
        a->start();
    }

    bool eventFilter(QObject *o, QEvent *e) override {
        if ((e->type() == QEvent::WindowActivate || e->type() == QEvent::WindowDeactivate) && o->isWidgetType()
            && o->property("appglass_f").toBool()) {
            auto *w = static_cast<QWidget *>(o);
            if (w->isWindow() && w->testAttribute(Qt::WA_TranslucentBackground))
                fade(w, e->type() == QEvent::WindowActivate);
        }
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
                c = withA(pal.win, level(w));
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
    Pal pal; double content, bar, inactive; int fadeMs; QEasingCurve::Type curve; bool glassDialogs; QStringList opaqueApps; bool dbg2 = false; mutable QSet<QObject*> seen;
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
