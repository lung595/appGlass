"""Dux Files (dfiles) and Dux Calendar (dcal): the apps' own glass keys.

Both apps are QtQuick (the DMS ``DCommon`` base) and already paint glass:
the window background, header and sidebar get alpha w =
``floatingWindowTransparency``, and panes drawn on top of it get
``floatingWindowForegroundTransparency`` f, so a pane lands at
1 - (1 - w)(1 - f). Text, icons and logos stay opaque. Colours follow DMS
live (dms-colors.json), so no colour file is written: appglass only merges
four keys into each app's ``ui-settings.json``:

  floatingWindowTransparency           = content level (DMS setting, 0.60)
  floatingWindowForegroundTransparency = dfiles 0.0 (uniform glass, config A)
                                         dcal 0.65 (panes 0.86, config B),
                                         raised if text would fall under 2:1
  floatingWindowForegroundLayers       = true
  blurEnabled                          = true

The apps' Settings pages write the same file, so the keys are merged in
place (same inode: dfiles watches the file and reloads live; dcal reads it
at start, restart it). A missing file is created and deleted again on
remove; an existing one gets its original bytes back.

Levels are inverted compared with the target (panes can only be at least
as opaque as the bars) and DDropdown menus take the window alpha; see
docs/qtquick.md.
"""

import json
import re

from ..core import TARGET as TEXT_TARGET  # opaque text roles
from ..core import Conflict, hex_to_rgb, luminance, worst_contrast

NAME = "dux"
APP_IDS = [r"^dev\.duxlabs\.files$", r"^dev\.duxlabs\.calendar$"]

DIM_TARGET = 2.0        # text with its own alpha by design (dcal onSurface_38)
DIM_ALPHA = 0.38        # dcal out-of-month day digits: Style.onSurface_38
TEXT_ROLES = ("on_surface", "on_surface_variant", "primary")


class App:
    def __init__(self, name, binary, config_dir, app_id, layer, dim_text):
        self.name = name                # also the APPGLASS_ASSUME_* name
        self.binary = binary
        self.config_dir = config_dir    # under $XDG_CONFIG_HOME
        self.app_id = app_id
        self.layer = layer              # floatingWindowForegroundTransparency
        self.dim_text = dim_text        # has text at DIM_ALPHA on the panes


APPS = (
    App("dfiles", "dfiles", "dfiles", APP_IDS[0], 0.0, False),
    App("dcal", "dcal", "dankcal", APP_IDS[1], 0.65, True),
)


def settings_path(env, app):
    return env.config_path(app.config_dir, "ui-settings.json")


def app_installed(env, app):
    """Per app: APPGLASS_ASSUME_(NOT_)INSTALLED take app names (dfiles, dcal)
    as well as the family name."""
    if app.name in env.assume_not_installed:
        return False
    if app.name in env.assume_installed or NAME in env.assume_installed:
        return True
    return env.which(app.binary) is not None


def installed(env):
    return any(app_installed(env, a) for a in APPS)


def stacked(w, f):
    """Alpha of a pane with alpha f drawn on the window background at w."""
    return 1.0 - (1.0 - w) * (1.0 - f)


def dim_contrast(fg_hex, bg_hex, alpha, text_alpha=DIM_ALPHA):
    """Worst contrast of text drawn at text_alpha on bg-at-alpha glass.

    The glass G is bg at alpha over a backdrop; the text pixel is
    text_alpha * fg + (1 - text_alpha) * G. Grey backdrops from black to
    white bound the real ones closely enough.
    """
    fg, bg = hex_to_rgb(fg_hex), hex_to_rgb(bg_hex)
    worst = None
    for b in range(0, 256, 5):
        g = [c * alpha + b * (1.0 - alpha) for c in bg]
        t = [text_alpha * x + (1.0 - text_alpha) * y for x, y in zip(fg, g)]
        lt, lg = luminance(t), luminance(g)
        c = (max(lt, lg) + 0.05) / (min(lt, lg) + 0.05)
        worst = c if worst is None else min(worst, c)
    return worst


def readable_layer(ctx, app, w):
    """The app's layer alpha, raised in 0.05 steps until its pane text reads."""
    bg = ctx.colors("surface")
    roles = [ctx.colors(r) for r in TEXT_ROLES]
    fg = ctx.colors("on_surface")

    def ok(f):
        a = stacked(w, f)
        if any(worst_contrast(c, bg, a) < TEXT_TARGET for c in roles):
            return False
        return not app.dim_text or dim_contrast(fg, bg, a) >= DIM_TARGET

    f = app.layer
    while not ok(f) and f < 1.0:
        f = min(1.0, round(f + 0.05, 2))
    return f


def verify_alphas(env, rec, level):
    """The hidden check (appglass verify): the pane alpha of the app at the
    window level, from the layer apply wrote (raised for text included), or
    none for a uniform fill. The panes cover most of a Dux Calendar window."""
    for app in APPS:
        if not re.match(app.app_id, rec.get("key") or "") and app.app_id not in (
                rec.get("app_ids") or ()):
            continue
        try:
            with open(settings_path(env, app)) as fh:
                f = float(json.load(fh).get("floatingWindowForegroundTransparency", app.layer))
        except (OSError, ValueError, TypeError, AttributeError):
            f = app.layer
        return [stacked(level, f)] if f > 0 else []
    return []


def keys(ctx, app):
    w = round(ctx.levels.content, 2)
    f = readable_layer(ctx, app, w)
    title = worst_contrast(ctx.colors("on_surface"), ctx.colors("surface"), w)
    if title < TEXT_TARGET:
        ctx.warn("%s: header text reaches only %.2f:1 at window alpha %.2f"
                 % (app.name, title, w))
    return {
        "floatingWindowTransparency": w,
        "floatingWindowForegroundTransparency": f,
        "floatingWindowForegroundLayers": True,
        "blurEnabled": True,
    }


def apply(ctx):
    env = ctx.env
    paths, ids = [], []
    for app in APPS:
        if not app_installed(env, app):
            continue
        p = settings_path(env, app)
        try:
            ctx.merge_json(p, keys(ctx, app))
        except Conflict as ex:
            ctx.warn("%s skipped: %s" % (app.name, ex))
            continue
        paths.append(p)
        ids.append(app.app_id)
    if not paths:
        raise Conflict("no Dux app could be configured")
    ctx.app_ids = ids
    return paths
