"""Kate: a KSyntaxHighlighting theme with a clear editor background.

The appglass Qt style (qt-style family, its launcher for org.kde.kate) paints
the window at the content level and, since B5b, clears WA_OpaquePaintEvent
on the children of glass windows. KTextEditor still fills its view and icon
border with the colour theme's background, opaque, over that glass. For each
installed Kate (native: $XDG_DATA_HOME; flatpak org.kde.kate:
~/.var/app/org.kde.kate/data):

- org.kde.syntax-highlighting/themes/appglass.theme (owned): the theme
  "AppGlass" from the DMS colours: BackgroundColor and IconBorder at alpha
  00 (the style's fill is the glass), the current line, selection and
  search marks as light tints, the text styles readable on the glass.

The theme is chosen only for the glass start, never in the user's katerc:
without the style nothing clears an alpha-0 background (black editor, old
text smeared after a scroll). Flatpak: ~/.var/app/org.kde.kate/config/
appglass/katerc (owned) sets ``[KTextEditor Renderer]`` ``Auto Color Theme
Selection[$i]=false`` and ``Color Theme[$i]=AppGlass``; the qt-style
launcher puts that dir in front of XDG_CONFIG_DIRS, KConfig cascades it under
the user's katerc and ``[$i]`` (immutable) wins over the user's own theme.
A plain ``flatpak run org.kde.kate`` never reads it, and the style takes the
dir out of XDG_CONFIG_DIRS once Kate runs (its terminal and tools never see
it). The user's katerc is not touched. A native Kate has no glass launcher:
it only gets the theme file (selectable by hand together with the style).

niri: ``^org\\.kde\\.kate$`` gets opacity 1.0 (the style paints the alpha).
"""

import json
import os

from . import _term
from ..core import mix, norm_hex, readable

NAME = "kate"
APP_IDS = [r"^org\.kde\.kate$"]
FLATPAK = "org.kde.kate"
CMDS = ("kate",)
THEME = "AppGlass"
SECTION = "KTextEditor Renderer"
KEYS = (("Auto Color Theme Selection", "false"), ("Color Theme", THEME))
XDG = "appglass"   # ~/.var/app/org.kde.kate/config/appglass: the glass start's katerc

# text style -> DMS role
STYLES = {
    "Normal": "on_surface", "Keyword": "primary", "Function": "secondary",
    "Variable": "tertiary", "ControlFlow": "primary", "Operator": "on_surface",
    "BuiltIn": "secondary", "Extension": "tertiary", "Preprocessor": "tertiary",
    "Attribute": "secondary", "Char": "tertiary", "SpecialChar": "error",
    "String": "tertiary", "VerbatimString": "tertiary", "SpecialString": "error",
    "Import": "primary", "DataType": "secondary", "DecVal": "error", "BaseN": "error",
    "Float": "error", "Constant": "error", "Comment": "on_surface_variant",
    "Documentation": "on_surface_variant", "Annotation": "secondary",
    "CommentVar": "secondary", "RegionMarker": "primary", "Information": "secondary",
    "Warning": "tertiary", "Alert": "error", "Others": "on_surface", "Error": "error",
}
BOLD = {"Keyword", "ControlFlow", "Import", "Alert", "Error"}
ITALIC = {"Comment", "Documentation"}


def installed(env):
    return bool(_term.targets(env, CMDS, FLATPAK))


def theme(ctx):
    lv = ctx.levels
    bg = norm_hex(ctx.colors("surface"))
    fg = norm_hex(ctx.colors("on_surface"))
    light = ctx.mode == "light"

    def text(role):
        return readable(norm_hex(ctx.colors(role)), bg, lv.content, _term.TARGET)

    def tint(a):  # #AARRGGBB, white (dark glass) or black (light glass)
        return "#%02x%s" % (a, "000000" if light else "ffffff")

    def argb(hexc, a):
        return "#%02x%s" % (a, norm_hex(hexc).lstrip("#"))

    styles = {}
    for name, role in STYLES.items():
        s = {"text-color": text(role), "selected-text-color": norm_hex(ctx.colors("on_primary_container"))}
        if name in BOLD:
            s["bold"] = True
        if name in ITALIC:
            s["italic"] = True
        styles[name] = s
    dim = readable(mix(fg, bg, 0.45), bg, lv.content, _term.TARGET)
    editor = {
        "BackgroundColor": argb(bg, 0), "IconBorder": argb(bg, 0),
        "CodeFolding": tint(0x1f), "BracketMatching": tint(0x24), "CurrentLine": tint(0x0d),
        "CurrentLineNumber": fg, "LineNumbers": dim, "IndentationLine": tint(0x1f),
        "MarkBookmark": norm_hex(ctx.colors("primary")), "MarkBreakpointActive": norm_hex(ctx.colors("error")),
        "MarkBreakpointDisabled": dim, "MarkBreakpointReached": norm_hex(ctx.colors("tertiary")),
        "MarkError": norm_hex(ctx.colors("error")), "MarkExecution": norm_hex(ctx.colors("secondary")),
        "MarkWarning": norm_hex(ctx.colors("tertiary")),
        "ModifiedLines": norm_hex(ctx.colors("tertiary")), "SavedLines": norm_hex(ctx.colors("secondary")),
        "ReplaceHighlight": argb(ctx.colors("tertiary_container"), 0xb0),
        "SearchHighlight": argb(ctx.colors("secondary_container"), 0xb0),
        "Separator": tint(0x24), "SpellChecking": norm_hex(ctx.colors("error")),
        "TabMarker": tint(0x24), "TemplateBackground": tint(0x14),
        "TemplateFocusedPlaceholder": tint(0x24), "TemplatePlaceholder": tint(0x14),
        "TemplateReadOnlyPlaceholder": tint(0x0d),
        "TextSelection": argb(ctx.colors("primary_container"), 0xc0),
        "WordWrapMarker": tint(0x24),
    }
    doc = {
        "_comment": " ".join(h.strip() for h in _term.header("", "Kate glass")),
        "metadata": {"name": THEME, "revision": 1, "license": "SPDX-License-Identifier: MIT",
                     "copyright": []},
        "text-styles": styles,
        "editor-colors": editor,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def xdg_dir(env):
    """The config dir the qt-style launcher puts in front of XDG_CONFIG_DIRS."""
    return _term.var_app(env, FLATPAK, "config", XDG)


def glass_rc():
    head = "".join("# %s\n" % h.strip() for h in _term.header("", "Kate glass start"))
    return head + "[%s]\n%s" % (SECTION, "".join("%s[$i]=%s\n" % kv for kv in KEYS))


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        paths.append(ctx.write_owned(
            t.data_path("org.kde.syntax-highlighting", "themes", "appglass.theme"), theme(ctx)))
        if t.kind == "flatpak":
            paths.append(ctx.write_owned(os.path.join(xdg_dir(ctx.env), "katerc"), glass_rc()))
    return paths
