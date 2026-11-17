"""Kate: a KSyntaxHighlighting theme with a clear editor background.

The appglass Qt style (qt-style family, its launcher for org.kde.kate) paints
the window at the content level and, since B5b, clears WA_OpaquePaintEvent
on the children of glass windows. KTextEditor still fills its view and icon
border with the colour theme's background, opaque, over that glass. For each
installed Kate (native: $XDG_DATA_HOME + $XDG_CONFIG_HOME/katerc; flatpak
org.kde.kate: ~/.var/app/org.kde.kate/{data,config}):

- org.kde.syntax-highlighting/themes/appglass.theme (owned): the theme
  "AppGlass" from the DMS colours: BackgroundColor and IconBorder at alpha
  00 (the style's fill is the glass), the current line, selection and
  search marks as light tints, the text styles readable on the glass.
- katerc (edited, backed up): ``[KTextEditor Renderer]`` ``Auto Color Theme
  Selection=false`` and ``Color Theme=AppGlass``. Kate rewrites katerc
  itself; a katerc changed since apply is left as it is, and remove takes
  the keys out only while they still name AppGlass.

niri: ``^org\\.kde\\.kate$`` gets opacity 1.0 (the style paints the alpha).
"""

import json
import os

from . import _term
from ..core import Conflict, mix, norm_hex, readable

NAME = "kate"
APP_IDS = [r"^org\.kde\.kate$"]
FLATPAK = "org.kde.kate"
CMDS = ("kate",)
THEME = "AppGlass"
SECTION = "KTextEditor Renderer"
KEYS = (("Auto Color Theme Selection", "false"), ("Color Theme", THEME))

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


def edit_rc(text):
    for k, v in KEYS:
        text = _term.ini_set(text, SECTION, k, v)
    return text


def undo(env, path, text):
    if os.path.basename(path) != "katerc":
        return text
    for k, v in KEYS:
        text = _term.ini_unset(text, SECTION, k, v)
    return text + "\n" if text and not text.endswith("\n") else text


def apply(ctx):
    paths = []
    for t in _term.targets(ctx.env, CMDS, FLATPAK):
        rc = t.config_path("katerc")
        if os.path.islink(rc):
            raise Conflict("%s is a symlink (user-managed); left untouched" % rc)
        paths.append(ctx.write_owned(
            t.data_path("org.kde.syntax-highlighting", "themes", "appglass.theme"), theme(ctx)))
        changed = ctx.changed_since_apply(rc)
        ctx.edit_text(rc, lambda text: text if changed else edit_rc(text),
                      undo=lambda text, p=rc: undo(ctx.env, p, text))
        paths.append(rc)
    return paths
