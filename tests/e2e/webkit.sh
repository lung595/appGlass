#!/usr/bin/env bash
# e2e: the generic WebKitGTK route (family webkit) on Kiri, in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/webkit.sh
#
# Kiri (a Tauri/wry app: GTK3 + WebKitGTK 4.1, no family of its own) runs
# with HOME and XDG_* in the harness TMP, no session/system bus (NOBUS=1),
# its daemon socket dir hidden (bwrap --tmpfs /run/kiri: it starts with no
# engine), the other engine sockets it names hidden too where they exist
# (/run/podman, $XDG_RUNTIME_DIR/podman and docker.sock, ~/.docker/run) with
# DOCKER_HOST unset, both systemd managers out of reach ($XDG_RUNTIME_DIR/systemd
# and /run/systemd empty tmpfs: sd-bus `systemctl --user` goes to the first
# whatever the bus address says; $XDG_RUNTIME_DIR/bus and the system bus
# /dev/null; before Kiri starts the e2e looks, under the same mask, that no
# bus path is a socket and no socket is left under either systemd dir: nothing
# real is asked), and no network (unshare -n when available; under it no host
# name may resolve: resolved's varlink socket is in /run/systemd).
# The zenity that takes the focus runs under the same mask. The user's Kiri
# data (~/.kiri, ~/.local/share/kiri) is only listed, before and after.
#
# 1. scratch sandbox: apply/remove round trip (whole tree back to the same
#    sha256), the rule file for the nested niri
# 2. the gate: a sandbox with the default settings (Kiri not switched on):
#    apply leaves Kiri waiting for its check, the real `appglass verify kiri`
#    (the hidden session: headless gamescope, its own niri, Kiri's language
#    step seeded, no network, /run/kiri hidden) passes, the next apply puts
#    the glass launcher in place; again with the DMS level sources at 0.80
#    (the glass rule and foregroundLayerTransparency): it passes at 204
# 2b. harness sandbox: apps.kiri.enabled (the user's own on: no hidden-session
#    check needed), appglass apply (+ idempotency): the launcher override
#    starts Kiri through appglass-webkit
# 3. Kiri with its language step done (~/.kiri/ui.json): shoot, measure the
#    content level (153), the bars and cards (166), text opaque, contrast on
#    the wallpaper; the glass window says it is not opaque (its last
#    wl_surface.set_opaque_region is nil, WAYLAND_DEBUG: at niri opacity 1.0
#    niri would skip what is behind it), and the rule file blends it at
#    0.999 too; at content 0.80, unfocused (another window has the
#    focus): the content eases to the inactive level, text still opaque
# 4. Kiri on a first start: its language dialog (role=dialog) is a popup,
#    opaque (255) over the glass
# 5. appglass remove: the sandbox is back to the pre-apply bytes (Kiri's own
#    files left out), the user's Kiri data unchanged

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=webkit-e2e-$$
APPID='^kiri$'
SYS=/usr/share/applications/kiri.desktop
[ -f "$SYS" ] || ag_die "Kiri not installed ($SYS)"
command -v bwrap >/dev/null || ag_die "bwrap not found"
# Kiri's dark theme (its CSS): text and muted text
TEXT=f2f0eb
MUTED=98a1ac

real_fp() {
    for d in "$HOME/.kiri" "${XDG_DATA_HOME:-$HOME/.local/share}/kiri"; do
        [ -d "$d" ] && find "$d" -maxdepth 2 -printf '%P %s %T@\n' 2>/dev/null | sort
    done
    true
}
REAL_FP0=$(real_fp)

seed() {
    ag_mkroot "$1"
    ag_seed_dms "$1"
    ag_seed_niri "$1"
    mkdir -p "$1/config/appglass"
    printf '{"apps":{"kiri":{"enabled":true}}}\n' > "$1/config/appglass/settings.json"
}

# 1. scratch round trip and the rule file
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
P0=$(ag_tree_hash "$PRE")
ag_appglass "$PRE" apply --only webkit --quiet || ag_die "pre-apply failed"
grep -q 'appglass-webkit kiri ' "$PRE/data/applications/kiri.desktop" \
    || ag_die "scratch: no kiri launcher override"
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" | grep -q 'kiri' || ag_die "the rule file has no kiri rule"
# the blend block (opacity 0.999): its GTK3 window says it is opaque without the shim
printf '%s\n' "$KDL" | awk '/says it is opaque/ {b = 1} b && /^}/ {exit} b && /\^kiri\$/ {k = 1}
    b && /opacity 0\.999/ {o = 1} END {exit !(k && o)}' || ag_die "kiri is not in the 0.999 blend block"
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"
ag_appglass "$PRE" remove >/dev/null || ag_die "pre-remove failed"
[ "$(ag_tree_hash "$PRE")" = "$P0" ] || ag_die "scratch round trip: tree differs after remove"

ag_start "$NAME" "$KDL"

# 2. the gate, then glass after the check; at the fixture's level, then at
# 0.80 (the DMS glass rule and foregroundLayerTransparency both at 0.80: the
# hidden session stages them and judges at the same level)
gate_check() {
    local lv=$1 want
    V=$(mktemp -d "$AG_OUT/gate.XXXX")
    ag_mkroot "$V"; ag_seed_dms "$V"; ag_seed_niri "$V"
    [ -z "$lv" ] || ag_set_level "$V" "$lv"
    ag_appglass "$V" apply --only webkit --quiet || ag_die "gate: apply failed"
    [ "$(kiri_state)" = waiting ] || ag_die "gate: kiri is $(kiri_state) before its check"
    grep -q appglass-webkit "$V/data/applications/kiri.desktop" 2>/dev/null \
        && ag_die "gate: a glass launcher before the check"
    # the private runtime dir of the check: a short path (sun_path)
    VB=$(mktemp -d "${TMPDIR:-/tmp}/agv.XXXX")
    chmod 700 "$VB"
    JM=$(ag_journal_mark)
    # niri: the nested one (verify asks it whether a game runs)
    VOUT=$(env -u WAYLAND_DISPLAY -u NIRI_CONFIG NIRI_SOCKET="$AG_SOCK" \
        APPGLASS_VERIFY_HARNESS=builtin APPGLASS_VERIFY_BASE="$VB" APPGLASS_VERIFY_KEEP="$AG_OUT" \
        APPGLASS_SANDBOX="$V" HOME="$V/home" XDG_CONFIG_HOME="$V/config" XDG_DATA_HOME="$V/data" \
        XDG_STATE_HOME="$V/state" XDG_CACHE_HOME="$V/cache" "$AG_BIN" verify kiri 2>&1) || true
    printf '%s\n' "$VOUT" > "$AG_OUT/verify${lv:+-$lv}.log"
    # a process of the check that crashed leaves no crash record (RLIMIT_CORE 1)
    CORES=$(ag_coredumps_since "$JM" '^(kiri|WebKit|gamescope|niri|Xwayland|dbus)')
    [ -z "$CORES" ] || ag_die "gate: systemd-coredump ran for the check: $CORES"
    LEFTV=$(ls -A "$VB"); rmdir "$VB" 2>/dev/null || true
    [ -z "$LEFTV" ] || ag_die "gate: the check left $LEFTV behind"
    printf '%s\n' "$VOUT" | grep -q '^verify: kiri: pass ' || ag_die "gate${lv:+ at $lv}: verify: $VOUT"
    if [ -n "$lv" ]; then
        want=$(python3 -c "print(round($lv * 255))")
        printf '%s\n' "$VOUT" | grep -q "want $want" \
            || ag_die "gate at $lv: not judged at $want: $VOUT"
    fi
    ag_appglass "$V" apply --only webkit --quiet || ag_die "gate: apply after the check failed"
    [ "$(kiri_state)" = glass ] || ag_die "gate: kiri is $(kiri_state) after its check"
    grep -q "^Exec=$V/home/.local/bin/appglass-webkit kiri " "$V/data/applications/kiri.desktop" \
        || ag_die "gate: no glass launcher after the check"
}
kiri_state() {
    ag_appglass "$V" status --json | jq -r '.apps[] | select(.key == "kiri") | .state'
}
gate_check ""
GATE="$(printf '%s' "$VOUT" | sed -n 's/^verify: kiri: //p' | head -1)"
gate_check 0.80
GATE80="$(printf '%s' "$VOUT" | sed -n 's/^verify: kiri: //p' | head -1)"

# 2b. the harness sandbox
SB=$AG_TMP
seed "$SB"
H0=$(ag_tree_hash "$SB")
ag_appglass "$SB" apply --only webkit || ag_die "apply failed"
L=$SB/data/applications/kiri.desktop
grep -q "^Exec=$SB/home/.local/bin/appglass-webkit kiri " "$L" || ag_die "launcher override missing"
H1=$(ag_tree_hash "$SB")
[ "$H1" != "$H0" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only webkit --quiet
[ "$(ag_tree_hash "$SB")" = "$H1" ] || ag_die "second apply is not idempotent"
ST=$(ag_appglass "$SB" status --json | jq -c '.apps[] | select(.key == "kiri")
     | {family, state, adapter, generic}')
[ "$ST" = '{"family":"webkit","state":"glass","adapter":"webkit-shim","generic":true}' ] \
    || ag_die "kiri route: $ST"

# the launcher's Exec as words (field codes dropped)
read -r -a EXEC <<< "$(sed -n 's/^Exec=//p' "$L" | head -1 | sed -E 's/(^| )%[a-zA-Z]//g')"
NONET=()
unshare -U --map-current-user -n true 2>/dev/null && NONET=("$(command -v unshare)" -U --map-current-user -n)
RT=${XDG_RUNTIME_DIR:-/nonexistent}
mapfile -t HIDE < <(ag_hide_args /run/kiri /run/podman "$RT/podman" "$RT/docker.sock" \
    "$HOME/.docker/run" "${AG_SESSION_SOCKETS[@]}" "${AG_SYSTEM_SOCKETS[@]}")
printf '%s\n' "${HIDE[@]}" | grep -qx /run/kiri || ag_die "no /run/kiri to hide"
ag_out_of_reach "${HIDE[@]}"
[ "${#NONET[@]}" = 0 ] || ag_no_dns bwrap --dev-bind / / "${HIDE[@]}" --die-with-parent "${NONET[@]}"
kiri_up() {   # [VAR=value ...]: more environment for Kiri
    NOBUS=1 ag_harness run "$NAME" -- env -u DOCKER_HOST "$@" bwrap --dev-bind / / "${HIDE[@]}" \
        --die-with-parent "${NONET[@]}" "${EXEC[@]}" >&2
    ag_wait_window "$NAME" "$APPID" 30 || { tail -20 "$SB/app.log" >&2 || true; ag_die "no Kiri window"; }
}
kiri_down() {
    local i
    ag_harness msg "$NAME" action close-window --id "$1" >/dev/null || true
    for i in $(seq 1 50); do
        ag_harness windows "$NAME" 2>/dev/null | grep -q '"kiri"' || return 0
        sleep 0.2
    done
    ag_die "Kiri did not quit"
}

# 3. the app, past its language step
mkdir -p "$SB/home/.kiri"
printf '{"langAsked":true}\n' > "$SB/home/.kiri/ui.json"
LOG0=$(wc -c < "$SB/app.log" 2>/dev/null || echo 0)
ID=$(kiri_up WAYLAND_DEBUG=client)
sleep 4
SHOT=$AG_OUT/kiri.png
ag_harness shot "$NAME" "$SHOT" "$ID" >&2
# each surface's last opaque region: nil on the glass window (GTK3 sets it
# whole from the window's CSS background; the shim clears it)
REGION_RC=0
tail -c +$((LOG0 + 1)) "$SB/app.log" | sed -n 's/.*-> \(wl_surface#[0-9]*\)\.set_opaque_region(\(.*\))$/\1 \2/p' \
    | awk '{last[$1] = $2} END {for (s in last) print s, last[s]}' > "$AG_OUT/opaque-region.txt"
[ -s "$AG_OUT/opaque-region.txt" ] || grep -q 'wl_surface#[0-9]*\.commit' "$SB/app.log" || REGION_RC=2
grep -qv ' nil$' "$AG_OUT/opaque-region.txt" && REGION_RC=1
# (Kiri's muted grey on 60% glass over white: 1.85:1, the page's own choice of grey)
args=(--content 153 --tol 6 --bar 166 --bar-tol 8 --text "$TEXT" --text "$MUTED" --min-contrast 1.8)
WP=$(ag_wallpaper); [ -n "$WP" ] && args+=(--wallpaper "$WP")
MEASURE_RC=0
ag_measure "$SHOT" "${args[@]}" --json "$AG_OUT/measure.json" > /dev/null || MEASURE_RC=$?

kiri_down "$ID"

# unfocused, at a content level the fade can lower (0.80: the inactive level
# 0.72; at 0.60 the floor leaves it as it is): another workspace takes the
# focus, the content eases down, text stays opaque
WR=$SB/config/niri/dms/windowrules.kdl
cp "$WR" "$AG_OUT/windowrules.kdl"
sed -i -E '0,/opacity 0\.[0-9]+/s//opacity 0.80/' "$WR"
LV=$(ag_appglass "$SB" levels)
HI=$(printf '%s' "$LV" | jq -r '.content * 255 | round')
INACT=$(printf '%s' "$LV" | jq -r '.inactive * 255 | round')
[ "$INACT" -lt "$HI" ] || ag_die "no inactive level below the content ($LV)"
ID=$(kiri_up)
sleep 4
FSHOT=$AG_OUT/kiri-focused-80.png
ag_harness shot "$NAME" "$FSHOT" "$ID" >&2
FADE_RC=0
ag_measure "$FSHOT" --content "$HI" --tol 6 --text "$TEXT" --min-contrast 1.5 \
    --json "$AG_OUT/measure-focused-80.json" > /dev/null || FADE_RC=$?
# another window takes the focus (zenity, else an empty workspace)
ZID=
if command -v zenity >/dev/null; then
    NOBUS=1 ag_harness run "$NAME" -- bwrap --dev-bind / / "${HIDE[@]}" --die-with-parent \
        zenity --info --title appglass-focus --text focus >&2
    ZID=$(ag_wait_window "$NAME" '^zenity$|^org\.gnome\.Zenity$' 20 || true)
fi
if [ -n "$ZID" ]; then
    ag_harness msg "$NAME" action focus-window --id "$ZID" >/dev/null
else
    ag_harness msg "$NAME" action focus-workspace-down >/dev/null
fi
sleep 1.5
USHOT=$AG_OUT/kiri-unfocused-80.png
ag_harness shot "$NAME" "$USHOT" "$ID" >&2
ag_measure "$USHOT" --content "$INACT" --tol 6 --text "$TEXT" --min-contrast 1.5 \
    --json "$AG_OUT/measure-unfocused.json" > /dev/null || FADE_RC=$?
if [ -n "$ZID" ]; then
    ag_harness msg "$NAME" action close-window --id "$ZID" >/dev/null || true
else
    ag_harness msg "$NAME" action focus-workspace-up >/dev/null
fi
kiri_down "$ID"
cp "$AG_OUT/windowrules.kdl" "$WR"

# 4. a first start: the language dialog over the glass
rm -f "$SB/home/.kiri/ui.json"
ID=$(kiri_up)
sleep 4
PSHOT=$AG_OUT/kiri-dialog.png
ag_harness shot "$NAME" "$PSHOT" "$ID" >&2
kiri_down "$ID"
POPUP_RC=0
python3 - "$SHOT" "$PSHOT" "$AG_OUT/popup.json" <<'PY' || POPUP_RC=$?
import json, subprocess, sys
def rgba(p):
    w, h = map(int, subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", p], text=True).strip().split(","))
    return w, h, subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", p,
                                          "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
def opaque_box(p):
    """The largest run of fully opaque rows in the middle column band: the dialog."""
    w, h, b = rgba(p)
    rows = []
    for y in range(h):
        row = b[(y * w + w // 4) * 4:(y * w + 3 * w // 4) * 4]
        rows.append(sum(1 for i in range(3, len(row), 4) if row[i] == 255) / (w // 2))
    best = cur = 0
    for r in rows:
        cur = cur + 1 if r >= 0.5 else 0
        best = max(best, cur)
    return h, best
h0, before = opaque_box(sys.argv[1])
h1, dialog = opaque_box(sys.argv[2])
rep = {"opaque_rows_glass": before, "opaque_rows_dialog": dialog, "height": h1}
rep["pass"] = dialog >= 0.2 * h1 and before < 0.05 * h0
json.dump(rep, open(sys.argv[3], "w"), indent=1)
sys.exit(0 if rep["pass"] else 1)
PY

# 5. remove: every file appglass wrote goes, the rest is as Kiri left it
ag_appglass "$SB" remove >/dev/null || ag_die "remove failed"
REMOVE_RC=0
LEFT=$(cd "$SB" && find config data state home cache -type f 2>/dev/null \
       | grep -E 'appglass-webkit|appglass/webkit|applications/kiri\.desktop|niri/appglass\.kdl' || true)
[ -z "$LEFT" ] || { REMOVE_RC=1; echo "left after remove: $LEFT" >&2; }
ag_stop_all
sleep 0.5

REAL_OK=1
[ "$REAL_FP0" = "$(real_fp)" ] || REAL_OK=0

python3 - "$AG_OUT/measure.json" "$AG_OUT/measure-unfocused.json" "$AG_OUT/popup.json" \
    "$REAL_OK" "$GATE" "$GATE80" <<'PY'
import json, os, sys
m = json.load(open(sys.argv[1]))
u = json.load(open(sys.argv[2])) if os.path.exists(sys.argv[2]) else {}
p = json.load(open(sys.argv[3])) if os.path.exists(sys.argv[3]) else {}
t = m.get("text", {})
print("content alpha mode %s (expected %s, share %.2f); bar px at %s: %s; glyph px min %s; "
      "min contrast %s; unfocused content mode %s (expected %s); dialog opaque rows %s/%s; "
      "real Kiri untouched: %s; gate: %s; gate at 0.80: %s"
      % (m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"],
         m.get("bar", {}).get("expected"), m.get("bar", {}).get("px"),
         min(v["glyph_alpha255_px"] for v in t.values()) if t else None,
         m.get("min_text_contrast"), u.get("content", {}).get("alpha_mode"),
         u.get("content", {}).get("expected"), p.get("opaque_rows_dialog"), p.get("height"),
         sys.argv[4] == "1", sys.argv[5], sys.argv[6]))
for f in m["fails"] + u.get("fails", []):
    print("  fail: " + f)
PY
[ "$MEASURE_RC" = 0 ] || ag_die "measurements failed (see $AG_OUT/measure.json)"
[ "$REGION_RC" != 2 ] || ag_die "no wayland requests in the app log (WAYLAND_DEBUG)"
[ "$REGION_RC" = 0 ] || ag_die "the glass window says it is opaque (see $AG_OUT/opaque-region.txt)"
[ "$FADE_RC" = 0 ] || ag_die "unfocused level wrong (see $AG_OUT/measure-unfocused.json)"
[ "$POPUP_RC" = 0 ] || ag_die "language dialog not opaque (see $AG_OUT/popup.json)"
[ "$REMOVE_RC" = 0 ] || ag_die "remove left files behind"
[ "$REAL_OK" = 1 ] || ag_die "the user's Kiri data changed"
echo "e2e webkit (kiri): PASS"
