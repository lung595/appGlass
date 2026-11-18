#!/usr/bin/env bash
# e2e: Lian Li Linux (family lianli: lianli-gui, Tauri / WebKitGTK) in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/lianli.sh
#
# lianli-gui runs with HOME and XDG_* in the harness TMP, no session/system
# bus (NOBUS=1), its daemon socket dir and locks hidden (/run/lianli* : the
# dir an empty tmpfs, the /run/lianli-*.lock files /dev/null; the fans and
# lights of the machine are never reached; the e2e dies without the dir), and
# both systemd managers out of reach. At startup the GUI runs
# `systemctl --user start --no-block lianli-session.service` and asks the
# system manager about lianli-control-recovery.service and the daemon units;
# sd-bus reaches the user manager by $XDG_RUNTIME_DIR/systemd/private and the
# system one by the system bus, whatever the bus addresses say. So
# $XDG_RUNTIME_DIR/systemd and /run/systemd are empty tmpfs,
# $XDG_RUNTIME_DIR/bus, the Lian Li session locks ($XDG_RUNTIME_DIR/lianli*)
# and /run/dbus/system_bus_socket are /dev/null, and before the app starts the
# e2e looks, under the same mask, that no bus path is a socket and no socket
# is left under either systemd dir (only paths: nothing real is asked). No
# network (unshare -n when available; under it no host name may resolve).
# The user's Lian Li data is only listed, before and after, and neither
# systemd manager may log a job line about a lianli-* unit while it runs (the
# real daemon's own log is not one).
#
# 1. scratch sandbox: apply/remove round trip (whole tree back to the same
#    sha256), the rule file for the nested niri
# 2. harness sandbox: apps.lianli.enabled, appglass apply: the launcher
#    override starts lianli-gui through appglass-lianli
# 3. shoot, measure the content level (153), the bars and cards (166) and
#    some opaque pixels (text, 255)
# 4. appglass remove: the sandbox is back to the pre-apply bytes (the app's
#    own files left out)

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=lianli-e2e-$$
APPID='^(com\.sgtaziz\.lianlilinux|lianli-gui)$'
DID=com.sgtaziz.lianlilinux.desktop
SYS=/usr/share/applications/$DID
[ -f "$SYS" ] || ag_die "Lian Li Linux not installed ($SYS)"
command -v lianli-gui >/dev/null || ag_die "lianli-gui not found"
command -v bwrap >/dev/null || ag_die "bwrap not found"

real_fp() {
    for d in "${XDG_CONFIG_HOME:-$HOME/.config}/lianli" "${XDG_DATA_HOME:-$HOME/.local/share}/com.sgtaziz.lianlilinux" \
             "${XDG_CONFIG_HOME:-$HOME/.config}/com.sgtaziz.lianlilinux"; do
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
    printf '{"apps":{"lianli":{"enabled":true}}}\n' > "$1/config/appglass/settings.json"
}
# the tree without the app's own files (what remove must bring back)
tree() {
    (cd "$1" && find . -type f ! -path './home/.cache/*' ! -path './cache/com.sgtaziz*' \
        ! -path './data/com.sgtaziz*' ! -path './config/com.sgtaziz*' ! -path './home/.local/share/com.sgtaziz*' \
        ! -path './cache/lianli*' ! -path './config/lianli*' ! -path './app.log' ! -path './niri.log' \
        ! -path './shots/*' ! -path './cache/nvidia/*' ! -path './cache/mesa*' ! -name 'niri.kdl' \
        -print0 | sort -z | xargs -0 -r sha256sum)
}

# 1. scratch round trip and the rule file
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
P0=$(ag_tree_hash "$PRE")
ag_appglass "$PRE" apply --only lianli --quiet || ag_die "pre-apply failed"
grep -q 'appglass-lianli' "$PRE/data/applications/$DID" || ag_die "scratch: no launcher override"
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" | grep -q 'lianli' || ag_die "the rule file has no Lian Li rule"
ag_appglass "$PRE" remove >/dev/null || ag_die "pre-remove failed"
[ "$(ag_tree_hash "$PRE")" = "$P0" ] || ag_die "scratch round trip: tree differs after remove"

# 2. the harness sandbox
ag_start "$NAME" "$KDL"
SB=$AG_TMP
seed "$SB"
H0=$(tree "$SB")
ag_appglass "$SB" apply --only lianli || ag_die "apply failed"
L=$SB/data/applications/$DID
grep -q "^Exec=.*$SB/home/.local/bin/appglass-lianli" "$L" || ag_die "launcher override missing"
ST=$(ag_appglass "$SB" status --json | jq -c '.apps[] | select(.key == "com.sgtaziz.lianlilinux")
     | {family, state, adapter}')
[ "$ST" = '{"family":"lianli","state":"glass","adapter":"webkit-shim"}' ] || ag_die "lianli route: $ST"

# 3. the app, its daemon out of reach
read -r -a EXEC <<< "$(sed -n 's/^Exec=//p' "$L" | head -1 | sed -E 's/(^| )%[a-zA-Z]//g')"
NONET=()
unshare -U --map-current-user -n true 2>/dev/null && NONET=("$(command -v unshare)" -U --map-current-user -n)
RT=${XDG_RUNTIME_DIR:-/nonexistent}
mapfile -t HIDE < <(ag_hide_args /run/lianli* "$RT"/lianli* "${AG_SESSION_SOCKETS[@]}" \
    "${AG_SYSTEM_SOCKETS[@]}")
printf '%s\n' "${HIDE[@]}" | grep -qx /run/lianli || ag_die "no /run/lianli to hide"
ag_out_of_reach "${HIDE[@]}"
[ "${#NONET[@]}" = 0 ] || ag_no_dns bwrap --dev-bind / / "${HIDE[@]}" --die-with-parent "${NONET[@]}"
JMARK=$(ag_journal_mark)
UJMARK=$(ag_user_journal_mark)
NOBUS=1 ag_harness run "$NAME" -- bwrap --dev-bind / / "${HIDE[@]}" --die-with-parent \
    "${NONET[@]}" "${EXEC[@]}" >&2
ID=$(ag_wait_window "$NAME" "$APPID" 30) || { ag_harness windows "$NAME" >&2 || true
    tail -20 "$SB/app.log" >&2 || true; ag_die "no Lian Li window"; }
# with no daemon the app soon lays its "Check your installation" dialog and a
# scrim over the page: the page is shot before that (the first shot that
# shows the page glass), the dialog after it (opaque over the glass)
SHOT=$AG_OUT/lianli.png
MEASURE_RC=1
for i in $(seq 1 12); do
    ag_harness shot "$NAME" "$AG_OUT/lianli-$i.png" "$ID" >&2
    if ag_measure "$AG_OUT/lianli-$i.png" --content 153 --tol 6 --bar 166 --bar-tol 8 \
            --json "$AG_OUT/measure-$i.json" > /dev/null; then
        cp "$AG_OUT/lianli-$i.png" "$SHOT"; cp "$AG_OUT/measure-$i.json" "$AG_OUT/measure.json"
        MEASURE_RC=0; break
    fi
    sleep 0.4
done
[ -f "$AG_OUT/measure.json" ] || cp "$AG_OUT/measure-$i.json" "$AG_OUT/measure.json"
ag_harness msg "$NAME" action close-window --id "$ID" >/dev/null || true
for _ in $(seq 1 50); do
    ag_harness windows "$NAME" 2>/dev/null | grep -qE 'lianlilinux|lianli-gui' || break
    sleep 0.2
done
ag_harness windows "$NAME" 2>/dev/null | grep -qE 'lianlilinux|lianli-gui' && ag_die "Lian Li did not quit"
sleep 1
JOURNAL=$(ag_journal_since "$JMARK" 'lianli-*')
printf '%s\n' "$JOURNAL" > "$AG_OUT/journal.txt"
UJOURNAL=$(ag_user_journal_since "$UJMARK" 'lianli-*')
printf '%s\n' "$UJOURNAL" > "$AG_OUT/journal-user.txt"

# 4. remove: the sandbox is back as it was (the app's own files aside)
ag_appglass "$SB" remove >/dev/null || ag_die "remove failed"
REMOVE_RC=0
H2=$(tree "$SB")
[ "$H2" = "$H0" ] || { REMOVE_RC=1; diff <(printf '%s\n' "$H0") <(printf '%s\n' "$H2") >&2 || true; }
ag_stop_all
sleep 0.5

REAL_OK=1
[ "$REAL_FP0" = "$(real_fp)" ] || REAL_OK=0

python3 - "$AG_OUT/measure.json" "$REAL_OK" "$([ -n "$JMARK" ] && echo "${JOURNAL:+entries}" || echo unread)" \
    "$([ -n "$UJMARK" ] && echo "${UJOURNAL:+entries}" || echo unread)" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print("content alpha mode %s (expected %s, share %.2f); bar px at %s: %s; opaque px: %s; "
      "real Lian Li untouched: %s; lianli-* units in the system journal: %s, in the user journal: %s"
      % (m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"],
         m.get("bar", {}).get("expected"), m.get("bar", {}).get("px"),
         m.get("opaque_px"), sys.argv[2] == "1", sys.argv[3] or "none", sys.argv[4] or "none"))
for f in m["fails"]:
    print("  fail: " + f)
PY
[ "$MEASURE_RC" = 0 ] || ag_die "measurements failed (see $AG_OUT/measure.json)"
[ "$REMOVE_RC" = 0 ] || ag_die "remove did not bring the sandbox back"
[ "$REAL_OK" = 1 ] || ag_die "the user's Lian Li data changed"
[ -n "$JMARK" ] || ag_die "the system journal is not readable: cannot show the units stayed quiet"
[ -z "$JOURNAL" ] || ag_die "the system manager ran lianli-* units while the GUI was up (see $AG_OUT/journal.txt)"
[ -n "$UJMARK" ] || ag_die "the user journal is not readable: cannot show the user units stayed quiet"
[ -z "$UJOURNAL" ] || ag_die "the user manager ran lianli-* units while the GUI was up (see $AG_OUT/journal-user.txt)"
echo "e2e lianli: PASS"
