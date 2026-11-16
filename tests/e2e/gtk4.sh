#!/usr/bin/env bash
# e2e: GTK4 / libadwaita glass in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/gtk4.sh
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file (+ a rule for the role window
#    below, which is a test app and not in the family's list)
# 2. sandbox = harness TMP: DMS settings/colours and gtk-4.0/dank-colors.css
#    (copies), a throwaway folder TMP/home/Demo; snapshot; appglass apply
# 3. Nautilus on the Demo folder (no session bus: NOBUS=1): content glass
#    (view) and sidebar at the bar level, opaque text >= 2:1
# 4. tests/e2e/adw_roles.py (libadwaita role window): raised headerbar,
#    sidebar and cards at the bar level; its menu popover opaque; an
#    AdwAlertDialog opaque (Nautilus menus need D-Bus actions, so they are
#    opened here)
# 5. appglass remove; every appglass-relevant file is byte-identical to the
#    snapshot (the apps' own runtime files are not ours)

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=gtk4-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
ROLES=$AG_E2E/adw_roles.py
ROLES_ID='^org\.appglass\.AdwRoles$'
NAUT_ID='^org\.gnome\.Nautilus$'

command -v nautilus >/dev/null || ag_die "nautilus not installed"
python3 -c 'import gi; gi.require_version("Adw", "1")' 2>/dev/null || ag_die "no libadwaita gi bindings"

seed() {
    local r=$1
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
    ag_copy_in "$(ag_real_config)/gtk-4.0/dank-colors.css" "$AG_FIX/gtk/dank-colors.css" \
        "$r/config/gtk-4.0/dank-colors.css"
    mkdir -p "$r/home/Demo/Photos" "$r/home/Demo/Projects"
    printf 'appglass e2e\n' > "$r/home/Demo/notes.txt"
    printf '# readme\n' > "$r/home/Demo/README.md"
    printf 'a,b\n1,2\n' > "$r/home/Demo/table.csv"
}

# hash of what appglass may touch, minus the apps' runtime files
RUNTIME_SKIP="config/nautilus data/nautilus data/gvfs-metadata data/recently-used.xbel state/nautilus data/gnome-software home/.cache home/.local"
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

# 1. the rule file, generated outside the session
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
ag_appglass "$PRE" apply --only gtk4 --quiet || ag_die "pre-apply failed"
grep -qF 'org\.gnome\.Nautilus' "$PRE/config/niri/appglass.kdl" || ag_die "no niri rule for Nautilus"
KDL=$(ag_extra_kdl "$PRE"; printf '\n// e2e role window (test app)\nwindow-rule {\n    match app-id=r#"%s"#\n    opacity 1.0\n}\n' "$ROLES_ID")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"

ag_start "$NAME" "$KDL"
SB=$AG_TMP

# 2. sandbox in the harness TMP
seed "$SB"
H0=$(g_hash "$SB" 2> "$AG_OUT/files-before-$RUN.txt")
ag_appglass "$SB" apply --only gtk4 || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
G=$SB/config/gtk-4.0
[ "$(cat "$G/gtk.css")" = "$(printf '@import url("dank-colors.css");\n@import url("dank-glass.css");')" ] \
    || ag_die "gtk.css is not the two imports"
H1=$(g_hash "$SB" 2>/dev/null)
[ "$H0" != "$H1" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only gtk4 --quiet
[ "$(g_hash "$SB" 2>/dev/null)" = "$H1" ] || ag_die "second apply is not idempotent"
cp "$G/dank-glass.css" "$AG_OUT/dank-glass-$RUN.css"

# expected levels and colours: dank-colors.css, then dank-glass.css (import order)
read -r CONTENT8 BAR8 FG POPOVER DIALOG < <(python3 -I - "$AG_REPO" "$SB" <<'PY'
import os, re, sys
sys.path.insert(0, sys.argv[1])
from appglass import core
r = sys.argv[2]
env = core.Env({"HOME": r + "/home", "XDG_CONFIG_HOME": r + "/config", "XDG_DATA_HOME": r + "/data",
                "XDG_STATE_HOME": r + "/state", "XDG_CACHE_HOME": r + "/cache",
                "APPGLASS_SANDBOX": r})
lv = core.Levels.from_env(env)
c = {}
for n in ("dank-colors.css", "dank-glass.css"):
    with open(os.path.join(r, "config", "gtk-4.0", n)) as f:
        for k, v in re.findall(r"@define-color\s+(\w+)\s+(#[0-9a-fA-F]{6})\s*;", f.read()):
            c[k] = v.lower()
print(lv.content8, lv.bar8, c["window_fg_color"], c["popover_bg_color"], c["dialog_bg_color"])
PY
)
[ -n "$DIALOG" ] || ag_die "could not read the expected colours"
ag_log "expected content $CONTENT8 bar $BAR8 text $FG popover $POPOVER dialog $DIALOG"
WP=$(ag_wallpaper); WPA=(); [ -n "$WP" ] && WPA=(--wallpaper "$WP")
BASE=(--content "$CONTENT8" --tol 6 --bar "$BAR8" --text "$FG" "${WPA[@]}")
FAILS=0

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
    ag_measure "$s" "$@" --json "$AG_OUT/measure-$l-run$RUN.json" > /dev/null || {
        FAILS=$((FAILS + 1)); ag_log "$l: measurements failed"; }
}

# 3. Nautilus
NOBUS=1 ag_harness run "$NAME" -- env ADW_DEBUG_COLOR_SCHEME=prefer-dark \
    nautilus --new-window "$SB/home/Demo" >&2
ID=$(ag_wait_window "$NAME" "$NAUT_ID" 30) || { tail -20 "$SB/app.log" >&2 || true; ag_die "no Nautilus window"; }
ag_harness msg "$NAME" action focus-window --id "$ID" >/dev/null
ag_harness msg "$NAME" action maximize-column >/dev/null
sleep 3
S=$(shoot nautilus "$ID")
measure nautilus "$S" "${BASE[@]}"
closewin "$ID"

# 4. the role window: plain shot + menu popover, then the alert dialog
NOBUS=1 ag_harness run "$NAME" -- env ADW_DEBUG_COLOR_SCHEME=prefer-dark \
    python3 -I "$ROLES" menu >&2
ID=$(ag_wait_window "$NAME" "$ROLES_ID" 20) || { tail -20 "$SB/app.log" >&2 || true; ag_die "no role window"; }
ag_harness msg "$NAME" action maximize-column >/dev/null
sleep 3
S=$(shoot roles-menu "$ID")
measure roles-menu "$S" "${BASE[@]}" --popup "$POPOVER"
closewin "$ID"

NOBUS=1 ag_harness run "$NAME" -- env ADW_DEBUG_COLOR_SCHEME=prefer-dark \
    python3 -I "$ROLES" dialog >&2
ID=$(ag_wait_window "$NAME" "$ROLES_ID" 20) || { tail -20 "$SB/app.log" >&2 || true; ag_die "no role window (dialog)"; }
ag_harness msg "$NAME" action maximize-column >/dev/null
sleep 3
S=$(shoot roles-dialog "$ID")
# the window behind the modal is dimmed (more opaque): only the dialog is checked
ag_measure "$S" --content "$CONTENT8" --solid "$DIALOG" --solid-min 5000 \
    --json "$AG_OUT/measure-roles-dialog-run$RUN.json" > /dev/null || true
jq -e --arg d "$DIALOG" '.solid[$d].alpha255_px >= 5000' "$AG_OUT/measure-roles-dialog-run$RUN.json" \
    >/dev/null || { FAILS=$((FAILS + 1)); ag_log "roles-dialog: dialog not opaque"; }
closewin "$ID"

# 5. remove
ag_appglass "$SB" remove || ag_die "remove failed"
H2=$(g_hash "$SB" 2> "$AG_OUT/files-after-$RUN.txt")
REMOVE_OK=1
[ "$H2" = "$H0" ] || REMOVE_OK=0
for f in gtk.css dank-glass.css; do [ -e "$G/$f" ] && REMOVE_OK=0; done
ag_stop_all

python3 -I - "$AG_OUT" "$RUN" "$REMOVE_OK" "$DIALOG" <<'PY'
import json, os, sys
out, run, ok, dlg = sys.argv[1:]
for l in ("nautilus", "roles-menu", "roles-dialog"):
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
    for k in ("popup", "solid"):
        for hx, v in m.get(k, {}).items():
            parts.append("%s %s opaque px %s" % (k, hx, v["alpha255_px"]))
    if t:
        parts.append("glyph px min %s, min contrast %s" % (
            min(v["glyph_alpha255_px"] for v in t.values()), m.get("min_text_contrast")))
    print("%s: %s" % (l, "; ".join(parts)))
    if l != "roles-dialog":
        for f in m["fails"]:
            print("  fail: " + f)
print("remove byte-identical: %s" % (ok == "1"))
PY
[ "$FAILS" = 0 ] || ag_die "$FAILS measurement set(s) failed (see $AG_OUT/measure-*-run$RUN.json)"
[ "$REMOVE_OK" = 1 ] || ag_die "remove left the sandbox different ($H0 != $H2)"
echo "e2e gtk4 run $RUN: PASS"
