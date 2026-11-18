#!/usr/bin/env bash
# e2e: Herdr glass in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/herdr.sh
#
# Herdr runs with everything in the harness TMP: HERDR_APP_HOME and XDG_* in
# TMP, its herdr-core on a socket in TMP (HC_SOCKET, own HC_SESSION), a PATH
# of a few whitelisted tools (no systemd-run/systemctl: the nested core is
# not registered with the user manager), no network (unshare -n when
# available), no session/system bus (NOBUS=1). The user's running Herdr, its
# core sockets and ~/.config/herdr-app are only read, before and after, to
# prove they did not change.
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file
# 2. sandbox = harness TMP; seed DMS settings/colours (copies); start Herdr
#    once so it writes its shipped layouts (main.json), quit it; snapshot;
#    appglass apply (+ idempotency)
# 3. start Herdr again, open a space running a demo (default text, the 16
#    ANSI colours), shoot, measure: content 153, bars 166, glyphs opaque,
#    contrast >= 2:1 on wallpaper/white/black; open the command palette,
#    shoot, the popup is opaque (255)
# 4. quit Herdr, appglass remove: every file appglass touched is back to the
#    pre-apply bytes (Herdr's own state changes from the run are listed and
#    left out); plus an apply/remove round trip without Herdr in a scratch
#    sandbox, compared by sha256 of the whole tree

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=herdr-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
APPID='^herdr-app$'

HERDR_BIN=$(command -v herdr-app || true)
[ -n "$HERDR_BIN" ] || HERDR_BIN=${XDG_DATA_HOME:-$HOME/.local/share}/herdr-app/herdr-app
HERDR_BIN=$(readlink -f "$HERDR_BIN" || true)
[ -x "$HERDR_BIN" ] || ag_die "herdr-app not installed"
CORE_BIN=$(command -v herdr-core || command -v hc || true)
[ -n "$CORE_BIN" ] || ag_die "herdr-core not found"

# --- the user's Herdr: read-only fingerprints, compared at the end
REAL_HOME=${HERDR_APP_HOME:-$(ag_real_config)/herdr-app}
REAL_RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/herdr-core
real_fp() {
    {
        ls -la --time-style=full-iso "$REAL_RT" 2>/dev/null | tail -n +4 || true
        pgrep -u "$(id -u)" -f -a '^(herdr-app|.*herdr-core (connect|serve|hold))' 2>/dev/null \
            | grep -v -- "$AG_OUT" | grep -v -- "${AG_TMP:-/nonexistent}" || true
        for f in shared.json settings.json layouts/main.json; do
            [ -f "$REAL_HOME/$f" ] && sha256sum "$REAL_HOME/$f"
        done
        ls "$REAL_HOME/themes" "$REAL_HOME/layouts" 2>/dev/null || true
    } | sort
}
REAL_FP0=$(real_fp)

seed() {
    local r=$1
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
}

# per-file manifest: rel path -> sha256 (or link target)
manifest() {
    python3 - "$1" <<'PY'
import hashlib, json, os, stat, sys
root = sys.argv[1]
out = {}
for top in ("config", "data", "state", "home", "cache/dms"):
    base = os.path.join(root, top)
    for dp, dns, fns in os.walk(base):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = "L " + os.readlink(p)
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as f:
                    out[rel] = hashlib.sha256(f.read()).hexdigest()
print(json.dumps(out, sort_keys=True))
PY
}

# 1. the rule file, generated outside the session (fixture main layout)
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
mkdir -p "$PRE/config/herdr-app/layouts"
cp "$AG_FIX/herdr/main.json" "$PRE/config/herdr-app/layouts/main.json"
cp "$AG_FIX/herdr/shared.json" "$PRE/config/herdr-app/shared.json"
P0=$(ag_tree_hash "$PRE")
ag_appglass "$PRE" apply --only herdr --quiet || ag_die "pre-apply failed"
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"
# round trip without Herdr: whole tree back to the same sha256
ag_appglass "$PRE" remove >/dev/null || ag_die "pre-remove failed"
P1=$(ag_tree_hash "$PRE")
[ "$P0" = "$P1" ] || ag_die "scratch round trip: tree differs after remove ($P0 != $P1)"
ag_appglass "$PRE" apply --only herdr --quiet || ag_die "pre-apply failed"

ag_start "$NAME" "$KDL"
SB=$AG_TMP
HH=$SB/config/herdr-app

# the confined launcher: tools whitelist, core socket in TMP, no network
mkdir -p "$SB/bin" "$SB/hc" "$SB/home/work"
chmod 700 "$SB/hc"
for c in sh bash env sleep printf ls cat; do
    t=$(PATH=/usr/bin:/bin command -v "$c") && ln -sf "$t" "$SB/bin/$c"
done
ln -sf "$CORE_BIN" "$SB/bin/herdr-core"
ln -sf "$CORE_BIN" "$SB/bin/hc"
NONET=()
unshare -U --map-current-user -n true 2>/dev/null && NONET=("$(command -v unshare)" -U --map-current-user -n)
LAUNCH=$AG_OUT/herdr-launch.sh
{
    echo '#!/bin/sh'
    echo "# Herdr confined to $SB"
    printf 'export HERDR_APP_HOME=%q HC_SOCKET=%q HC_SESSION=%q\n' "$HH" "$SB/hc/default.sock" "$NAME"
    printf 'export PATH=%q SHELL=%q HERDR_APP_LOG=%q\n' "$SB/bin" "$SB/bin/sh" "$SB/herdr-app.log"
    echo 'export HERDR_TELEMETRY=0 DO_NOT_TRACK=1 HERDR_APP_NO_SOUND=1'
    echo 'export HERDR_RELEASES_URL=http://127.0.0.1:9 HERDR_FEEDBACK_URL=http://127.0.0.1:9 HERDR_TELEMETRY_URL=http://127.0.0.1:9'
    printf 'exec %s %q "$@"\n' "${NONET[*]:-}" "$HERDR_BIN"
} > "$LAUNCH"
chmod +x "$LAUNCH"
hdo() { "$LAUNCH" do "$@" >/dev/null; }

herdr_up() {
    ag_run "$NAME" "$LAUNCH" >&2
    ag_wait_window "$NAME" "$APPID" 30 || { tail -20 "$SB/app.log" >&2 || true; ag_die "no Herdr window"; }
}
herdr_down() {
    local i
    hdo window.close || true
    for i in $(seq 1 75); do
        if ! ag_harness windows "$NAME" 2>/dev/null | grep -q '"herdr-app"' \
                && [ ! -e "$HH/herdr-app.sock" ]; then
            return 0
        fi
        sleep 0.2
    done
    ag_harness windows "$NAME" 2>/dev/null | grep -q '"herdr-app"' && ag_die "Herdr did not quit"
    rm -f "$HH/herdr-app.sock"      # left behind by the exited app
}

# 2. sandbox in the harness TMP; Herdr's first start writes its shipped files
seed "$SB"
mkdir -p "$HH"
printf '{"telemetry":false,"zoom":1}\n' > "$HH/settings.json"
printf '{"frame.welcomed":"finished"}' > "$HH/shared.json"
herdr_up >/dev/null
sleep 2
herdr_down
[ -f "$HH/layouts/main.json" ] || ag_die "Herdr wrote no layouts/main.json"
manifest "$SB" > "$AG_OUT/m0.json"
cp "$HH/shared.json" "$AG_OUT/shared0.json"
H0=$(ag_tree_hash "$SB")
ag_appglass "$SB" apply --only herdr || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
[ "$(jq -r .layout "$HH/shared.json")" = appglass ] || ag_die "shared.json layout not set"
H1=$(ag_tree_hash "$SB")
[ "$H0" != "$H1" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only herdr --quiet
[ "$(ag_tree_hash "$SB")" = "$H1" ] || ag_die "second apply is not idempotent"
manifest "$SB" > "$AG_OUT/m1.json"

TH=$HH/themes/appglass.json
EXP=$(jq -c '{fg: .foreground, muted: .colors.muted, dim: .colors.dim, ansi: .ansi,
      canvas: .colors.canvas, chrome: .colors.chrome}' "$TH")
printf '%s\n' "$EXP" > "$AG_OUT/expected-$RUN.json"
j() { printf '%s' "$EXP" | jq -r "$1"; }
CONTENT=$((16#$(j .canvas | cut -c8-9)))
BAR=$((16#$(j .chrome | cut -c8-9)))

# 3. the app, with a demo terminal
DEMO=$AG_OUT/demo.sh
cat > "$DEMO" <<'EOF'
#!/bin/sh
printf '\033[?25l'
printf 'appglass e2e: default text on the glass, The quick brown fox 0123456789 \342\226\210\342\226\210\342\226\210\n\n'
for s in 3 9; do
    i=0
    while [ $i -lt 8 ]; do
        printf '\033[%s%dm%s%d \342\226\210\342\226\210\342\226\210\342\226\210 \033[0m' $s $i $s $i
        i=$((i + 1))
    done
    echo
done
exec sleep 600
EOF
chmod +x "$DEMO"
ID=$(herdr_up)
hdo space.new --name demo --folder "$SB/home/work" --argv "[\"$DEMO\"]" || ag_die "space.new failed"
sleep 3
SHOT=$AG_OUT/herdr-run$RUN.png
ag_harness shot "$NAME" "$SHOT" "$ID" >&2

args=(--content "$CONTENT" --tol 6 --bar "$BAR" --bar-tol 8
      --text "$(j .fg)" --text "$(j .muted)" --text "$(j .dim)")
for i in 1 2 3 4 5 6 7 9 10 11 12 13 14 15; do args+=(--text "$(j ".ansi[$i]")"); done
WP=$(ag_wallpaper); [ -n "$WP" ] && args+=(--wallpaper "$WP")
MEASURE_RC=0
ag_measure "$SHOT" "${args[@]}" --json "$AG_OUT/measure-run$RUN.json" > /dev/null || MEASURE_RC=$?

# popups: the command palette, opaque over the glass
hdo app.palette || ag_die "app.palette failed"
sleep 1.5
PSHOT=$AG_OUT/herdr-palette-run$RUN.png
ag_harness shot "$NAME" "$PSHOT" "$ID" >&2
POPUP_RC=0
python3 - "$SHOT" "$PSHOT" "$AG_OUT/popup-run$RUN.json" <<'PY' || POPUP_RC=$?
import collections, json, subprocess, sys
def rgba(p):
    return subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", p,
                                    "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
a, b = rgba(sys.argv[1]), rgba(sys.argv[2])
changed = [i for i in range(0, len(a), 4) if a[i:i + 4] != b[i:i + 4]]
alphas = collections.Counter(b[i + 3] for i in changed)
fill = collections.Counter(bytes(b[i:i + 3]).hex() for i in changed if b[i + 3] == 255)
top = fill.most_common(1)[0] if fill else ("", 0)
op = alphas.get(255, 0) / max(len(changed), 1)
rep = {"changed_px": len(changed), "opaque_share": round(op, 3),
       "popup_fill": "#" + top[0], "popup_fill_px": top[1], "alpha_hist": alphas.most_common(6)}
rep["pass"] = len(changed) > 20000 and op >= 0.85 and top[1] > 20000
json.dump(rep, open(sys.argv[3], "w"), indent=1)
sys.exit(0 if rep["pass"] else 1)
PY
POPUP=$(jq -r .popup_fill "$AG_OUT/popup-run$RUN.json")
# the popup fill and its text measured like the glass (alpha 255)
if [ "$POPUP_RC" = 0 ]; then
    ag_measure "$PSHOT" --content "$CONTENT" --tol 6 --popup "$POPUP" --solid-min 20000 \
        --text "$(j .fg)" --json "$AG_OUT/measure-palette-run$RUN.json" > /dev/null || POPUP_RC=$?
fi
herdr_down

# 4. re-apply (as the matugen hook does on a DMS theme change) with Herdr's
#    run edits in shared.json, then remove: Herdr's keys must survive
cp "$HH/shared.json" "$AG_OUT/shared-herdr.json"
ag_appglass "$SB" apply --only herdr --quiet || ag_die "re-apply failed"
manifest "$SB" > "$AG_OUT/m2.json"
ag_appglass "$SB" remove || ag_die "remove failed"
manifest "$SB" > "$AG_OUT/m3.json"
H3=$(ag_tree_hash "$SB")
REMOVE_RC=0
python3 - "$AG_OUT" "$SB" "$RUN" <<'PY' || REMOVE_RC=$?
import hashlib, json, os, sys
out, sb, run = sys.argv[1:4]
m = [json.load(open(os.path.join(out, "m%d.json" % i))) for i in range(4)]
m0, m1, m2, m3 = m
herdr_own = sorted(p for p in set(m1) | set(m2) if m1.get(p) != m2.get(p))
ours = sorted(p for p in set(m0) | set(m1) if m0.get(p) != m1.get(p))
fails = []
for p in ours:
    if p in herdr_own:
        continue
    if m3.get(p) != m0.get(p):
        fails.append("%s not restored" % p)
# files Herdr rewrote while appglass was applied: only our keys go back
shared = "config/herdr-app/shared.json"
if shared in herdr_own:
    with open(os.path.join(sb, shared)) as f:
        now = json.load(f)
    with open(os.path.join(out, "shared0.json")) as f:
        was = json.load(f)
    with open(os.path.join(out, "shared-herdr.json")) as f:
        herdr_v = json.load(f)
    want_shared = {k: v for k, v in herdr_v.items() if k != "layout"}
    if "layout" in was:
        want_shared["layout"] = was["layout"]
    if now != want_shared:
        fails.append("shared.json after remove %r, want %r (Herdr's keys, our layout undone)"
                     % (now, want_shared))
# everything else: as Herdr left it
for p in set(m2) | set(m3):
    if p in ours or p == shared:
        continue
    if m3.get(p) != m2.get(p):
        fails.append("%s changed by remove" % p)
# the pre-apply tree with Herdr's own run changes folded in, as a sha256
want = dict(m0)
for p in herdr_own:
    if p in ours:
        continue
    if p in m2:
        want[p] = m2[p]
    else:
        want.pop(p, None)
got = {p: v for p, v in m3.items() if p != shared}
want.pop(shared, None)
h = lambda d: hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
rep = {"appglass_paths": ours, "herdr_changed_during_run": herdr_own,
       "pre_apply_sha256": h(want), "after_remove_sha256": h(got), "fails": fails}
if h(want) != h(got):
    fails.append("tree after remove differs from the pre-apply tree")
json.dump(rep, open(os.path.join(out, "remove-run%s.json" % run), "w"), indent=1)
sys.exit(1 if fails else 0)
PY
ag_stop_all
sleep 0.5

# the user's Herdr is exactly as before
REAL_FP1=$(real_fp)
REAL_OK=1
[ "$REAL_FP0" = "$REAL_FP1" ] || { REAL_OK=0; diff <(echo "$REAL_FP0") <(echo "$REAL_FP1") >&2 || true; }

python3 - "$AG_OUT/measure-run$RUN.json" "$AG_OUT/popup-run$RUN.json" \
    "$AG_OUT/remove-run$RUN.json" "$REAL_OK" <<'PY'
import json, os, sys
m = json.load(open(sys.argv[1]))
p = json.load(open(sys.argv[2])) if os.path.exists(sys.argv[2]) else {}
r = json.load(open(sys.argv[3])) if os.path.exists(sys.argv[3]) else {}
t = m.get("text", {})
print("content alpha mode %s (expected %s, share %.2f); bar px at %s: %s; popup %s opaque "
      "share %s (%s px); glyph px min %s; min contrast %s; remove restores pre-apply: %s "
      "(herdr's own run changes: %d files); real Herdr untouched: %s"
      % (m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"],
         m.get("bar", {}).get("expected"), m.get("bar", {}).get("px"),
         p.get("popup_fill"), p.get("opaque_share"), p.get("popup_fill_px"),
         min(v["glyph_alpha255_px"] for v in t.values()) if t else None,
         m.get("min_text_contrast"), not r.get("fails", ["?"]),
         len(r.get("herdr_changed_during_run", [])), sys.argv[4] == "1"))
for f in m["fails"] + r.get("fails", []):
    print("  fail: " + f)
PY
[ "$MEASURE_RC" = 0 ] || ag_die "measurements failed (see $AG_OUT/measure-run$RUN.json)"
[ "$POPUP_RC" = 0 ] || ag_die "popup not opaque (see $AG_OUT/popup-run$RUN.json)"
[ "$REMOVE_RC" = 0 ] || ag_die "remove did not restore the sandbox (see $AG_OUT/remove-run$RUN.json)"
[ "$REAL_OK" = 1 ] || ag_die "the user's Herdr state changed"
echo "e2e herdr run $RUN: PASS"
