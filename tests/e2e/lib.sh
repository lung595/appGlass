# appglass e2e helpers, sourced by tests/e2e/<family>.sh.
#
# Needs APPGLASS_HARNESS: path of the nested-niri harness script
# (start/run/windows/msg/shot/stop). Nothing here touches the real session:
# the apps run in the nested niri the harness starts, and every appglass call
# runs with APPGLASS_SANDBOX, HOME and XDG_* pointing into the harness TMP.
#
# APPGLASS_E2E_OUT: where shots and work files go (default: a new temp dir).

set -euo pipefail

AG_E2E=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AG_REPO=$(cd "$AG_E2E/../.." && pwd)
AG_BIN=$AG_REPO/bin/appglass
AG_FIX=$AG_REPO/tests/fixtures
AG_SESSIONS=()

ag_die() { echo "e2e: FAIL: $*" >&2; exit 1; }
ag_log() { echo "e2e: $*" >&2; }

ag_require() {
    [ -n "${APPGLASS_HARNESS:-}" ] || ag_die "set APPGLASS_HARNESS to the nested-niri harness script"
    [ -x "$APPGLASS_HARNESS" ] || ag_die "APPGLASS_HARNESS=$APPGLASS_HARNESS is not executable"
    for c in niri ffmpeg ffprobe python3 jq; do
        command -v "$c" >/dev/null || ag_die "$c not found"
    done
    AG_OUT=${APPGLASS_E2E_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/appglass-e2e.XXXXXX")}
    mkdir -p "$AG_OUT"
    trap ag_cleanup EXIT
}

ag_harness() { "$APPGLASS_HARNESS" "$@"; }

# real (read-only) inputs; fixtures when missing
ag_real_config() { echo "${XDG_CONFIG_HOME:-$HOME/.config}"; }
ag_real_cache() { echo "${XDG_CACHE_HOME:-$HOME/.cache}"; }
ag_real_state() { echo "${XDG_STATE_HOME:-$HOME/.local/state}"; }

ag_wallpaper() {
    local s wp
    s=$(ag_real_state)/dms/session.json
    wp=$( [ -f "$s" ] && jq -r '.wallpaperPath // empty' "$s" || true)
    [ -n "$wp" ] && [ -f "$wp" ] && echo "$wp" || echo ""
}

# A sandbox root with the XDG layout the harness uses: <root>/{home,config,data,state,cache}
ag_mkroot() {
    local r=$1
    mkdir -p "$r"/{home,config,data,state,cache}
}

# ag_appglass <root> args...: bin/appglass confined to <root>
ag_appglass() {
    local r=$1; shift
    env -u WAYLAND_DISPLAY -u NIRI_SOCKET -u NIRI_CONFIG \
        APPGLASS_SANDBOX="$r" HOME="$r/home" \
        XDG_CONFIG_HOME="$r/config" XDG_DATA_HOME="$r/data" \
        XDG_STATE_HOME="$r/state" XDG_CACHE_HOME="$r/cache" \
        "$AG_BIN" "$@"
}

# copy a real file (read-only) or the fixture into the sandbox
ag_copy_in() {
    local real=$1 fixture=$2 dest=$3
    mkdir -p "$(dirname "$dest")"
    if [ -f "$real" ]; then cp -- "$real" "$dest"; else cp -- "$fixture" "$dest"; fi
}

ag_seed_dms() {
    local r=$1
    ag_copy_in "$(ag_real_config)/dms/settings.json" "$AG_FIX/dms/settings.json" \
        "$r/config/dms/settings.json"
    ag_copy_in "$(ag_real_cache)/dms/dms-colors.json" "$AG_FIX/dms/dms-colors.json" \
        "$r/cache/dms/dms-colors.json"
}

ag_seed_niri() {
    local r=$1
    mkdir -p "$r/config/niri/dms"
    cp "$AG_FIX/niri/config.kdl" "$r/config/niri/config.kdl"
    cp "$AG_FIX/niri/dms/windowrules.kdl" "$r/config/niri/dms/windowrules.kdl"
}

# sha256 over paths, types and contents of the appglass-relevant sandbox trees
# (config, data, state, home, cache/dms; app caches like fontconfig are not ours)
ag_tree_hash() {
    local r=$1
    python3 - "$r" <<'PY'
import hashlib, os, sys
root = sys.argv[1]
h = hashlib.sha256()
for top in ("config", "data", "state", "home", "cache/dms"):
    base = os.path.join(root, top)
    for dp, dns, fns in os.walk(base):
        dns.sort()
        h.update(b"D " + os.path.relpath(dp, root).encode() + b"\n")
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).encode()
            if os.path.islink(p):
                h.update(b"L " + rel + os.readlink(p).encode() + b"\n")
            else:
                with open(p, "rb") as f:
                    h.update(b"F " + rel + hashlib.sha256(f.read()).digest() + b"\n")
print(h.hexdigest())
PY
}

# The niri rules of the user's session: the global Glass blur rule (DMS
# windowrules.kdl) followed by the appglass.kdl generated in <root>.
ag_extra_kdl() {
    local r=$1
    cat "$AG_FIX/niri/dms/windowrules.kdl"
    echo
    cat "$r/config/niri/appglass.kdl"
}

# ag_start <name> <extra_kdl>: sets AG_TMP (harness TMP) and AG_WL (nested display)
# The harness finds the nested wayland-N socket by diffing the runtime dir; a
# stale socket of the same name hides it and the session gets no display. Such
# a session is stopped and started once more under the same name; a second
# miss fails, so no client is ever launched with an empty WAYLAND_DISPLAY.
ag_start() {
    local n=$1 kdl=$2 out try
    for try in 1 2; do
        out=$(EXTRA_KDL=$kdl ag_harness start "$n") || { echo "$out" >&2; ag_die "harness start $n"; }
        AG_SESSIONS+=("$n")
        AG_TMP=$(printf '%s\n' "$out" | sed -n 's/^TMP=//p')
        AG_WL=$(printf '%s\n' "$out" | sed -n 's/^WL=//p')
        [ -n "$AG_TMP" ] && [ -d "$AG_TMP" ] || ag_die "no TMP from harness start: $out"
        if [ -n "$AG_WL" ]; then
            ag_log "started $n (WL=$AG_WL TMP=$AG_TMP)"
            return 0
        fi
        ag_log "session $n has no wayland display (try $try), stopping it"
        ag_harness stop "$n" >&2 || true
        ag_forget "$n"
    done
    ag_die "nested niri $n never got a wayland display (WL empty in its run env; a stale wayland-N socket in the runtime dir?)"
}

ag_forget() {
    local k keep=()
    for k in "${AG_SESSIONS[@]}"; do [ "$k" = "$1" ] || keep+=("$k"); done
    AG_SESSIONS=("${keep[@]}")
}

ag_stop_all() {
    local n
    for n in "${AG_SESSIONS[@]}"; do ag_harness stop "$n" >&2 || true; done
    AG_SESSIONS=()
}

ag_cleanup() {
    local rc=$?
    ag_stop_all
    exit $rc
}

# ag_wait_window <name> <app_id regex> [timeout s] -> window id
ag_wait_window() {
    local n=$1 re=$2 t=${3:-20} id i
    for i in $(seq 1 $((t * 5))); do
        id=$(ag_harness windows "$n" 2>/dev/null | jq -r --arg re "$re" \
            'select(.app_id != null and (.app_id | test($re))) | .id' | head -1 || true)
        [ -n "$id" ] && { echo "$id"; return 0; }
        sleep 0.2
    done
    return 1
}

ag_measure() { python3 "$AG_E2E/measure.py" "$@"; }
