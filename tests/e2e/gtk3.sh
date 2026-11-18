#!/usr/bin/env bash
# e2e: GTK3 glass (AppGlass theme, mode B) in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] [APPGLASS_E2E_LEVEL=0.80] tests/e2e/gtk3.sh
#
# APPGLASS_E2E_LEVEL sets the content level in the sandbox (at 0.60, the
# DMS default, the unfocused level is the same and there is no fade to see)
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file (+ a rule for the role
#    window below, a test app that is not in the family's list)
# 2. sandbox = harness TMP: DMS settings/colours and gtk-3.0/dank-colors.css
#    (copies); snapshot; appglass apply: theme, launcher overrides, the
#    Solaar autostart copy, no global gtk-3.0/gtk.css
# 3. the apps are started with the Exec line of the launcher override
#    (env GTK_THEME=AppGlass ...), with no session bus (NOBUS=1):
#    * Solaar --window=show, inside bwrap with an empty /dev so it cannot
#      reach the real Logitech receivers (it shows its "no device" view)
#    * nvidia-settings (HOME is the sandbox: ~/.nvidia-settings-rc untouched)
#    * tests/e2e/gtk3_roles.py: headerbar/menubar/toolbar/sidebar at the bar
#      level and an opaque popover
#    content glass, bars, opaque text >= 2:1
#    * unfocused: a second role window takes the focus; the first one's
#      background is at the inactive level (the CSS fade), its text opaque
# 4. appglass remove; every appglass-relevant file is byte-identical to the
#    snapshot (the apps' own runtime files are not ours)

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=gtk3-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
ROLES=$AG_E2E/gtk3_roles.py
ROLES_ID='^org\.appglass\.Gtk3Roles$'
# system .desktop sources only (read-only), never the user's own data dirs
export XDG_DATA_DIRS=/usr/local/share:/usr/share XDG_CONFIG_DIRS=/etc/xdg

command -v solaar >/dev/null || ag_die "solaar not installed"
command -v bwrap >/dev/null || ag_die "bwrap not found"
python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null || ag_die "no GTK3 gi bindings"
HAVE_NV=0; command -v nvidia-settings >/dev/null && HAVE_NV=1

seed() {
    local r=$1
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
    [ -z "${APPGLASS_E2E_LEVEL:-}" ] || ag_set_level "$r" "$APPGLASS_E2E_LEVEL"
    ag_copy_in "$(ag_real_config)/gtk-3.0/dank-colors.css" "$AG_FIX/gtk/dank-colors.css" \
        "$r/config/gtk-3.0/dank-colors.css"
}

# hash of what appglass may touch, minus the apps' runtime files
RUNTIME_SKIP="config/solaar data/recently-used.xbel home/.nvidia-settings-rc home/.cache home/.local"
g_hash() {
    python3 -I - "$1" "$RUNTIME_SKIP" <<'PY'
import hashlib, os, sys
root, skip = sys.argv[1], set(sys.argv[2].split())
h = hashlib.sha256()
for top in ("config", "data", "state", "home", "cache/dms"):
    for dp, dns, fns in os.walk(os.path.join(root, top)):
        rel = os.path.relpath(dp, root)
        dns[:] = sorted(d for d in dns if os.path.join(rel, d) not in skip)
        h.update(b"D " + rel.encode() + b"\n")
        for fn in sorted(fns):
            r = os.path.join(rel, fn)
            if r in skip:
                continue
            p = os.path.join(root, r)
            if os.path.islink(p):
                h.update(b"L " + r.encode() + os.readlink(p).encode() + b"\n")
            else:
                with open(p, "rb") as f:
                    h.update(b"F " + r.encode() + hashlib.sha256(f.read()).digest() + b"\n")
            print(r, file=sys.stderr)
print(h.hexdigest())
PY
}

# Exec= of a .desktop file as words, field codes (%u, %F ...) dropped
exec_of() {
    sed -n 's/^Exec=//p' "$1" | head -1 | sed -E 's/(^| )%[a-zA-Z]//g'
}

# 1. the rule file, generated outside the session
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
ag_appglass "$PRE" apply --only gtk3 --quiet || ag_die "pre-apply failed"
grep -q 'solaar' "$PRE/config/niri/appglass.kdl" || ag_die "no niri rule for solaar"
KDL=$(ag_extra_kdl "$PRE"; printf '\n// e2e role window (test app)\nwindow-rule {\n    match app-id=r#"%s"#\n    opacity 1.0\n}\n' "$ROLES_ID")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"

ag_start "$NAME" "$KDL"
SB=$AG_TMP

# 2. sandbox in the harness TMP
seed "$SB"
H0=$(g_hash "$SB" 2> "$AG_OUT/files-before-$RUN.txt")
ag_appglass "$SB" apply --only gtk3 || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
THEME=$SB/data/themes/AppGlass/gtk-3.0/gtk.css
L_SOLAAR=$SB/data/applications/solaar.desktop
L_NV=$SB/data/applications/nvidia-settings.desktop
[ -f "$THEME" ] || ag_die "no AppGlass theme"
[ -e "$SB/config/gtk-3.0/gtk.css" ] && ag_die "a global gtk-3.0/gtk.css was written"
grep -q '^Exec=env GTK_THEME=AppGlass solaar' "$L_SOLAAR" || ag_die "solaar launcher override missing"
if [ -f /etc/xdg/autostart/solaar.desktop ]; then
    grep -q '^Exec=env GTK_THEME=AppGlass solaar' "$SB/config/autostart/solaar.desktop" \
        || ag_die "solaar autostart override missing"
fi
[ "$HAVE_NV" = 0 ] || grep -q '^Exec=env GTK_THEME=AppGlass nvidia-settings' "$L_NV" \
    || ag_die "nvidia-settings launcher override missing"
H1=$(g_hash "$SB" 2>/dev/null)
[ "$H0" != "$H1" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only gtk3 --quiet
[ "$(g_hash "$SB" 2>/dev/null)" = "$H1" ] || ag_die "second apply is not idempotent"
cp "$THEME" "$AG_OUT/AppGlass-gtk.css-$RUN"

# expected levels and colours: dank-colors.css, then the theme's overrides; text from
# the Adwaita stylesheet the theme imports
read -r CONTENT8 BAR8 FG POPOVER DISABLED UNFOCUSED8 < <(python3 -I - "$AG_REPO" "$SB" "$THEME" <<'PY'
import os, re, sys
sys.path.insert(0, sys.argv[1])
from appglass import core
r = sys.argv[2]
env = core.Env({"HOME": r + "/home", "XDG_CONFIG_HOME": r + "/config", "XDG_DATA_HOME": r + "/data",
                "XDG_STATE_HOME": r + "/state", "XDG_CACHE_HOME": r + "/cache",
                "APPGLASS_SANDBOX": r})
lv = core.Levels.from_env(env)
c = {}
for p in (os.path.join(r, "config", "gtk-3.0", "dank-colors.css"), sys.argv[3]):
    with open(p) as f:
        for k, v in re.findall(r"@define-color\s+(\w+)\s+(#[0-9a-fA-F]{6})\s*;", f.read()):
            c[k] = v.lower()
# label text is the stock Adwaita foreground (its CSS compiles colours to literals)
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk  # noqa: F401  (registers the GTK resources)
base = re.search(r'resource://(/org/gtk/libgtk/theme/Adwaita/[\w.-]+\.css)', open(sys.argv[3]).read())
css = Gio.resources_lookup_data(base.group(1), 0).get_data().decode()
fg = re.search(r"@define-color\s+theme_fg_color\s+(#[0-9a-fA-F]{6})", css).group(1).lower()
# label:disabled (Solaar's "Select a device"): mix(@window_fg_color, @window_bg_color, 0.20)
wf, wb = c["window_fg_color"], c["window_bg_color"]
dis = "#" + "".join("%02x" % round(int(wf[i:i + 2], 16) * 0.8 + int(wb[i:i + 2], 16) * 0.2)
                    for i in (1, 3, 5))
from appglass import inactive, settings
p = inactive.params(settings.load(env)[0])
unf = inactive.level(lv.content, p["factor"]) if p["enabled"] else lv.content
print(lv.content8, lv.bar8, fg, c["popover_bg_color"], dis, round(unf * 255))
PY
)
[ -n "$UNFOCUSED8" ] || ag_die "could not read the expected colours"
ag_log "expected content $CONTENT8 bar $BAR8 text $FG disabled text $DISABLED popover $POPOVER unfocused $UNFOCUSED8"
WP=$(ag_wallpaper); WPA=(); [ -n "$WP" ] && WPA=(--wallpaper "$WP")
BASE=(--content "$CONTENT8" --tol 6 --text "$FG" "${WPA[@]}")
FAILS=0
DONE=()

shoot() {   # shoot <label> <window id> -> $AG_OUT/<label>-run$RUN.png
    local s=$AG_OUT/$1-run$RUN.png i
    rm -f "$s"
    for i in 1 2 3; do
        ag_harness shot "$NAME" "$s" "$2" >&2 && [ -s "$s" ] && { echo "$s"; return 0; }
        ag_log "shot $1: attempt $i failed"; sleep 1
    done
    echo "$s"
}
closewin() { ag_harness msg "$NAME" action close-window --id "$1" >/dev/null 2>&1 || true; sleep 1; }
measure() {   # measure <label> <shot> args...
    local l=$1 s=$2; shift 2
    DONE+=("$l")
    ag_measure "$s" "$@" --json "$AG_OUT/measure-$l-run$RUN.json" > /dev/null || {
        FAILS=$((FAILS + 1)); ag_log "$l: measurements failed"; }
}
show() {   # show <label> <app id regex> <timeout> cmd... -> window id, maximized
    local l=$1 re=$2 t=$3 id; shift 3
    ag_run "$NAME" "$@" >&2
    id=$(ag_wait_window "$NAME" "$re" "$t") || { tail -20 "$SB/app.log" >&2 || true; return 1; }
    ag_harness msg "$NAME" action focus-window --id "$id" >/dev/null
    ag_harness msg "$NAME" action maximize-column >/dev/null
    sleep 3
    echo "$id"
}

# 3a. Solaar, from its launcher override, with an empty /dev
read -r -a CMD <<< "$(exec_of "$L_SOLAAR")"
ID=$(show solaar '^solaar$' 30 bwrap --dev-bind / / --dev /dev --die-with-parent -- \
    "${CMD[@]}" --window=show) || ag_die "no Solaar window"
measure solaar "$(shoot solaar "$ID")" "${BASE[@]}" --text "$DISABLED"
closewin "$ID"

# 3b. nvidia-settings, from its launcher override
NV_NOTE="nvidia-settings not installed"
if [ "$HAVE_NV" = 1 ]; then
    read -r -a CMD <<< "$(exec_of "$L_NV")"
    if ID=$(show nvidia-settings '^nvidia-settings$' 30 "${CMD[@]}"); then
        measure nvidia-settings "$(shoot nvidia-settings "$ID")" "${BASE[@]}" --bar "$BAR8"
        closewin "$ID"
        NV_NOTE=""
    else
        NV_NOTE="nvidia-settings showed no window (the role window stands in)"
    fi
fi
[ -n "$NV_NOTE" ] && ag_log "$NV_NOTE"

# 3c. the role window: bars and an opaque popover
ID=$(show roles-popover "$ROLES_ID" 20 env GTK_THEME=AppGlass python3 -I "$ROLES" popover) \
    || ag_die "no role window"
measure roles-popover "$(shoot roles-popover "$ID")" "${BASE[@]}" --bar "$BAR8" --popup "$POPOVER"
closewin "$ID"

# 3d. unfocused: a second role window takes the focus, the first one fades
# its own background (window.background:backdrop, a CSS transition) and keeps
# its text opaque, at the focused colour
ID=$(show roles-unfocused "$ROLES_ID" 20 env GTK_THEME=AppGlass python3 -I "$ROLES" plain) \
    || ag_die "no role window"
measure roles-focused "$(shoot roles-focused "$ID")" "${BASE[@]}"
ag_run "$NAME" env GTK_THEME=AppGlass python3 -I "$ROLES" plain >&2
ID2=""
for _ in $(seq 1 100); do
    ID2=$(ag_harness windows "$NAME" 2>/dev/null | jq -r --arg re "$ROLES_ID" --argjson id "$ID" \
        'select(.app_id != null and (.app_id | test($re)) and .id != $id) | .id' | head -1 || true)
    [ -n "$ID2" ] && break
    sleep 0.2
done
[ -n "$ID2" ] || ag_die "no second role window"
ag_harness msg "$NAME" action focus-window --id "$ID2" >/dev/null
sleep 2
[ "$(ag_harness msg "$NAME" -j focused-window | jq -r .id)" = "$ID2" ] \
    || ag_die "the second role window did not take the focus"
if [ "$UNFOCUSED8" -lt "$CONTENT8" ]; then
    measure roles-unfocused "$(shoot roles-unfocused "$ID")" --content "$UNFOCUSED8" --tol 6 --text "$FG" "${WPA[@]}"
else
    # no fade at this level: the old unfocused cues (Adwaita's backdrop text)
    measure roles-unfocused "$(shoot roles-unfocused "$ID")" --content "$CONTENT8" --tol 6 --glyph-min 0 "${WPA[@]}"
    ag_log "no fade at content $CONTENT8 (APPGLASS_E2E_LEVEL=0.80 shows it)"
fi
closewin "$ID2"
closewin "$ID"

# 4. remove
ag_appglass "$SB" remove || ag_die "remove failed"
H2=$(g_hash "$SB" 2> "$AG_OUT/files-after-$RUN.txt")
REMOVE_OK=1
[ "$H2" = "$H0" ] || REMOVE_OK=0
for f in "$THEME" "$L_SOLAAR" "$L_NV" "$SB/config/autostart/solaar.desktop"; do
    [ -e "$f" ] && REMOVE_OK=0
done
ag_stop_all

python3 -I - "$AG_OUT" "$RUN" "$REMOVE_OK" "${DONE[@]}" <<'PY'
import json, os, sys
out, run, ok = sys.argv[1:4]
for l in sys.argv[4:]:
    f = os.path.join(out, "measure-%s-run%s.json" % (l, run))
    if not os.path.exists(f):
        print("%s: no measurement (no shot)" % l)
        continue
    m = json.load(open(f))
    t = m.get("text", {})
    parts = ["content mode %s (expected %s, share %.2f)" % (
        m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"])]
    if "bar" in m:
        parts.append("bar px %s at %s" % (m["bar"]["px"], m["bar"]["expected"]))
    for hx, v in m.get("popup", {}).items():
        parts.append("popup %s opaque px %s" % (hx, v["alpha255_px"]))
    if t:
        parts.append("glyph px min %s, min contrast %s" % (
            min(v["glyph_alpha255_px"] for v in t.values()), m.get("min_text_contrast")))
    print("%s: %s" % (l, "; ".join(parts)))
    for f in m["fails"]:
        print("  fail: " + f)
print("remove byte-identical: %s" % (ok == "1"))
PY
[ "$FAILS" = 0 ] || ag_die "$FAILS measurement set(s) failed (see $AG_OUT/measure-*-run$RUN.json)"
[ "$REMOVE_OK" = 1 ] || ag_die "remove left the sandbox different ($H0 != $H2)"
echo "e2e gtk3 run $RUN${NV_NOTE:+ ($NV_NOTE)}: PASS"
