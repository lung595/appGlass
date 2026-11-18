#!/usr/bin/env bash
# e2e: Obsidian glass in a nested niri, on a throwaway vault.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/obsidian.sh
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file
# 2. sandbox = harness TMP: DMS settings/colours (copies), a vault with two
#    notes in TMP/home/vault, Obsidian's own obsidian.json (its user data dir
#    is TMP/config/obsidian) listing only that vault; snapshot; appglass apply
# 3. run the Obsidian binary of the installed flatpak directly (never through
#    `flatpak run`, which would use ~/.var/app), inside bwrap --unshare-net
#    with tests/e2e/obsidian_cdp.py driving it over a debug port that only
#    exists in that private network namespace. No session bus (NOBUS=1).
# 4. open the note, maximize, shoot, measure: content glass, bar glass (per
#    region, from DOM rects), opaque text >= 2:1 (normal, muted, faint,
#    accent, and the code block's operators and numbers, which use the named
#    colours --color-red / --color-purple), palette/menu/notice opaque
# 5. quit Obsidian, appglass remove; every appglass-relevant file is
#    byte-identical to the snapshot (Obsidian's own runtime files are not ours)
#
# Obsidian's main process unlinks $XDG_RUNTIME_DIR/.obsidian-cli.sock and
# listens there at every start (no check for a live owner). The test instance
# sees the runtime dir read-only (bwrap --ro-bind, in its own mount namespace;
# sockets still connect), so its CLI server just fails to listen and nothing
# is created, replaced or removed in the real runtime dir. The run checks that
# both CLI socket paths are unchanged afterwards.

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=obsidian-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
APPID='^md\.obsidian\.Obsidian$'
CDP=$AG_E2E/obsidian_cdp.py
RUNTIME=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
CLISOCK=$RUNTIME/.obsidian-cli.sock
FLATSOCK=$RUNTIME/.flatpak/md.obsidian.Obsidian/xdg-run/.obsidian-cli.sock

command -v bwrap >/dev/null || ag_die "bwrap not found"
OBS=${APPGLASS_OBSIDIAN_BIN:-}
if [ -z "$OBS" ]; then
    for d in "${XDG_DATA_HOME:-$HOME/.local/share}/flatpak" /var/lib/flatpak; do
        f=$d/app/md.obsidian.Obsidian/current/active/files/obsidian
        [ -x "$f" ] && { OBS=$f; break; }
    done
fi
[ -n "$OBS" ] && [ -x "$OBS" ] || ag_die "no Obsidian binary (flatpak md.obsidian.Obsidian or APPGLASS_OBSIDIAN_BIN)"

sockstat() { stat -c '%i %Y' "$1" 2>/dev/null || echo absent; }
CLI0=$(sockstat "$CLISOCK")
FLAT0=$(sockstat "$FLATSOCK")

cleanup() {
    local rc=$?
    # a clean quit lets the nested niri stop cleanly
    set +e
    [ -n "${SB:-}" ] && [ -d "$SB/cdp" ] && python3 -I "$CDP" call "$SB/cdp" QUIT 20 >/dev/null 2>&1
    ag_stop_all
    [ "$(sockstat "$FLATSOCK")" = "$FLAT0" ] || { ag_log "FAIL: the flatpak Obsidian CLI socket changed"; rc=1; }
    [ "$(sockstat "$CLISOCK")" = "$CLI0" ] || { ag_log "FAIL: $CLISOCK changed"; rc=1; }
    exit $rc
}
trap cleanup EXIT

seed() {
    local r=$1 v=$1/home/vault
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
    mkdir -p "$v/.obsidian" "$r/config/obsidian"
    cat > "$v/Note.md" <<'MD'
# appglass test note

Paragraph text on the glass. The quick brown fox jumps over the lazy dog 0123456789.
A [[Second]] internal link and an [external link](https://example.invalid).

- list item one
- list item two

```js
// a code comment in faint text
const total = 4242 + 1717 * 9696 - 3838 / 1212;
if (total >= 9000 && total !== 0) total += 8080;
```
MD
    printf '# Second\n\nMuted.\n' > "$v/Second.md"
    # Obsidian's own format (2-space indent, no final newline), with the key
    # it adds on first start, so it has no reason to rewrite the file
    printf '{\n  "theme": "obsidian",\n  "showRibbon": true\n}' > "$v/.obsidian/appearance.json"
    printf '{"vaults":{"a1b2c3d4e5f60718":{"path":"%s","ts":1,"open":true}}}' "$v" \
        > "$r/config/obsidian/obsidian.json"
}

# hash of the whole sandbox (config, data, state, cache, home) except the
# files Obsidian/Electron itself writes while it runs: its user data dir, the
# vault's workspace/cache files (not appearance.json or snippets/) and the
# GPU driver's shader cache; each path is printed to stderr
ob_hash() {
    python3 -I - "$1" <<'PY'
import hashlib, os, re, sys
root = sys.argv[1]
runtime = re.compile(r"^(config/obsidian(/|$)"
                     r"|home/vault/\.obsidian/(?!appearance\.json$|snippets(/|$))"
                     r"|cache/(nvidia|mesa_shader_cache[^/]*)(/|$))")
h = hashlib.sha256()
for top in ("config", "data", "state", "cache", "home"):
    for dp, dns, fns in os.walk(os.path.join(root, top)):
        rel = os.path.relpath(dp, root)
        dns[:] = sorted(d for d in dns if not runtime.match(os.path.join(rel, d)))
        h.update(b"D " + rel.encode() + b"\n")
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            r = os.path.relpath(p, root)
            if runtime.match(r):
                continue
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
ag_appglass "$PRE" apply --only obsidian --quiet || ag_die "pre-apply failed"
grep -q 'md\\.obsidian\\.Obsidian' "$PRE/config/niri/appglass.kdl" || ag_die "no niri rule"
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"

ag_start "$NAME" "$KDL"
SB=$AG_TMP
VAULT=$SB/home/vault

# 2. sandbox in the harness TMP
seed "$SB"
H0=$(ob_hash "$SB" 2> "$AG_OUT/files-before-$RUN.txt")
ag_appglass "$SB" apply --only obsidian || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
CSS=$VAULT/.obsidian/snippets/appglass.css
[ -f "$CSS" ] || ag_die "no snippet"
jq -e '.enabledCssSnippets == ["appglass"] and .theme == "obsidian"' \
    "$VAULT/.obsidian/appearance.json" >/dev/null || ag_die "appearance.json not merged"
H1=$(ob_hash "$SB" 2>/dev/null)
ag_appglass "$SB" apply --only obsidian --quiet
[ "$(ob_hash "$SB" 2>/dev/null)" = "$H1" ] || ag_die "second apply is not idempotent"
cp "$CSS" "$AG_OUT/appglass-$RUN.css"

# expected levels and text colours
read -r CONTENT8 BAR8 < <(python3 -I - "$AG_REPO" "$SB" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from appglass import core
r = sys.argv[2]
env = core.Env({"HOME": r + "/home", "XDG_CONFIG_HOME": r + "/config", "XDG_DATA_HOME": r + "/data",
                "XDG_STATE_HOME": r + "/state", "XDG_CACHE_HOME": r + "/cache",
                "APPGLASS_SANDBOX": r})
lv = core.Levels.from_env(env)
print(lv.content8, lv.bar8)
PY
)
cssvar() { grep -oP -- "--$1: \K#[0-9a-f]{6}" "$CSS" | head -1; }
TEXTS=()
for v in text-normal text-muted text-faint text-accent color-red color-purple; do
    c=$(cssvar "$v"); [ -n "$c" ] || ag_die "no --$v in the snippet"; TEXTS+=("$c")
done
OPERATOR=$(cssvar color-red) NUMBER=$(cssvar color-purple)

# 3. the app
mkdir -p "$SB/cdp"
mapfile -t MASK < <(ag_mask_args) && [ "${#MASK[@]}" -gt 0 ] || ag_die "no mask for the app"
NOBUS=1 ag_harness run "$NAME" -- bwrap --dev-bind / / "${MASK[@]}" --ro-bind "$RUNTIME" "$RUNTIME" \
    --unshare-net --die-with-parent -- \
    python3 -I "$CDP" serve "$SB/cdp" -- "$OBS" --ozone-platform=wayland --no-sandbox \
    --enable-features=WaylandWindowDecorations >&2
ID=$(ag_wait_window "$NAME" "$APPID" 40) || { tail -20 "$SB/app.log" >&2 || true; ag_die "no Obsidian window"; }

js() { python3 -I "$CDP" call "$SB/cdp" "$@"; }
ready=""
for i in $(seq 1 60); do
    ready=$(js 'return !!(window.app && app.workspace && app.workspace.layoutReady
        && getComputedStyle(document.body).getPropertyValue("--ag-content").trim())' 5 || true)
    [ "$ready" = true ] && break
    sleep 0.5
done
[ "$ready" = true ] || { tail -20 "$SB/app.log" >&2 || true; ag_die "vault not ready or snippet not loaded"; }
js 'return [...app.customCss.enabledSnippets].includes("appglass")' | grep -qx true \
    || ag_die "Obsidian did not enable the snippet"
js 'await app.workspace.openLinkText("Note", "", false); return true' >/dev/null || ag_die "cannot open the note"
ag_harness msg "$NAME" action maximize-column >&2 || true
# Chromium paints only on the nested niri's frame callbacks, and the nested
# niri gets frames only while its window is in view on the host, so painting
# can stall for a while: wait for a run of real frames before every shot.
PAINT='const t0 = performance.now(), frame = () => Promise.race([
    new Promise(r => requestAnimationFrame(() => r(true))), new Promise(r => setTimeout(() => r(false), 3000))]);
  let w = -1, run = 0;
  while (performance.now() - t0 < 240000) {
    if (innerWidth !== w) { w = innerWidth; run = 0; }
    run = (await frame()) ? run + 1 : 0;
    if (run >= 6 && (!need || document.querySelector(need))) {
      await new Promise(r => setTimeout(r, 300));
      return Math.round(performance.now() - t0);
    }
  }
  return false'
paint() {   # paint [css selector that must exist] -> ms waited
    local r; r=$(js "const need = $(printf '%s' "${1:-}" | jq -Rs .);
$PAINT" 260) && [ "$r" != false ] || {
        js 'return {visibility: document.visibilityState, focus: document.hasFocus(), w: innerWidth}' >&2 || true
        ag_die "Obsidian painted no frames for 240 s (nested niri out of view on the host?)"; }
    echo "$r"
}
FR=$(paint ".mod-root .markdown-source-view, .mod-root .markdown-reading-view")
ag_log "painted after maximize (${FR} ms)"
# the code block's operators and numbers are drawn in the snippet's named
# colours (--code-operator: var(--color-red), --code-value: var(--color-purple))
FR=$(paint ".mod-root .cm-operator, .mod-root .token.operator")
ACC=$(js 'const hex = c => "#" + c.match(/\d+/g).slice(0, 3).map(n => (+n).toString(16).padStart(2, "0")).join("");
    const col = s => [...new Set([...document.querySelectorAll(".mod-root " + s)]
        .map(e => hex(getComputedStyle(e).color)))];
    return {operator: col(".cm-operator, .token.operator"), number: col(".cm-number, .token.number")}') \
    || ag_die "cannot read the code token colours"
ag_log "code token colours: $ACC (snippet: operator $OPERATOR, number $NUMBER)"
echo "$ACC" | jq -e --arg o "$OPERATOR" --arg n "$NUMBER" \
    '.operator == [$o] and .number == [$n]' >/dev/null \
    || ag_die "code operators/numbers do not use the snippet's --color-red/--color-purple ($ACC)"

# finite animations (the notice slides in) end before the rects are read
RECTS='await Promise.all(document.getAnimations().filter(a => a.playState === "running"
    && a.effect && a.effect.getComputedTiming().endTime !== Infinity).map(a => a.finished.catch(() => 0)));
  return {w: innerWidth, h: innerHeight, r: Object.fromEntries(
  ARGS.map(([k, s]) => { const e = document.querySelector(s); if (!e) return [k, null];
    const b = e.getBoundingClientRect(); return [k, [b.x, b.y, b.width, b.height]]; }))}'
rects() {   # rects <json array of [name, selector]> -> JSON
    js "${RECTS/ARGS/$1}"
}
shot() {    # shot <tag> <rects json array>: the rects must fit the shot (same layout)
    local t=$1 png=$AG_OUT/$1-run$RUN.png rj=$AG_OUT/$1-rects-$RUN.json i
    for i in 1 2 3 4 5 6; do
        rects "$2" > "$rj" || ag_die "rects for $t"
        paint >/dev/null
        ag_harness shot "$NAME" "$png" "$ID" >/dev/null || ag_die "shot $t"
        python3 -I - "$png" "$rj" <<'PY' && return 0
import json, subprocess, sys
w, h = map(int, subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
    "stream=width,height", "-of", "csv=p=0", sys.argv[1]]).decode().split(","))
r = json.load(open(sys.argv[2]))
dx, dy = w - r["w"], h - r["h"]
sys.exit(0 if dx == dy and 0 <= dx <= 64 and dx % 2 == 0 else 1)
PY
        sleep 1
    done
    ag_die "shot $t never matched the page size"
}

shot main '[["ribbon", ".workspace-ribbon"], ["sidebar", ".mod-left-split"],
  ["tabbar", ".mod-root .workspace-tab-header-container"], ["controls", ".titlebar-button-container.mod-right"],
  ["header", ".workspace-leaf.mod-active .view-header"], ["content", ".mod-root .view-content"],
  ["statusbar", ".status-bar"], ["vaultbar", ".workspace-sidedock-vault-profile"],
  ["navoff", ".workspace-leaf.mod-active .view-header-nav-buttons [aria-disabled=true]"]]'
# disabled icons are dimmed by colour, never by opacity
NAVOFF=$(js 'return [...document.querySelectorAll(".clickable-icon[aria-disabled=true]")]
    .map(e => getComputedStyle(e).opacity)') || ag_die "cannot read the disabled icons"
ag_log "disabled icon opacities: $NAVOFF"
echo "$NAVOFF" | jq -e 'length > 0 and all(. == "1")' >/dev/null \
    || ag_die "a disabled icon has an opacity ($NAVOFF)"

js 'const m = app.internalPlugins.getPluginById("command-palette").instance.modal; m.open();
    await new Promise(r => setTimeout(r, 800)); return !!document.querySelector(".prompt")' | grep -qx true \
    || ag_die "palette did not open"
shot palette '[["palette", ".prompt"]]'
js 'app.internalPlugins.getPluginById("command-palette").instance.modal.close();
    await new Promise(r => setTimeout(r, 500));
    const e = document.querySelector(".nav-file-title"); const b = e.getBoundingClientRect();
    e.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true,
      clientX: b.x + 60, clientY: b.y + 10, button: 2}));
    await new Promise(r => setTimeout(r, 600)); return !!document.querySelector(".menu")' | grep -qx true \
    || ag_die "file menu did not open"
shot menu '[["menu", ".menu"]]'
js 'document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", code: "Escape", keyCode: 27, bubbles: true}));
    document.querySelector(".menu")?.remove(); new Notice("appglass notice text", 0);
    await new Promise(r => setTimeout(r, 600)); return !!document.querySelector(".notice")' | grep -qx true \
    || ag_die "no notice"
shot notice '[["notice", ".notice"]]'
# colours Obsidian hard-codes instead of deriving them from --color-*: the
# notice text (#FAFAFA, for a dark surface in both themes) on the opaque
# notice, and the quote callout's title (#9e9e9e)
HARD=$(js 'const hex = c => "#" + c.match(/\d+/g).slice(0, 3).map(n => (+n).toString(16).padStart(2, "0")).join("");
    const n = getComputedStyle(document.querySelector(".notice"));
    const d = document.createElement("div"); d.className = "callout"; d.dataset.callout = "quote";
    d.innerHTML = "<div class=callout-title><div class=callout-title-inner>q</div></div>";
    document.querySelector(".mod-root .view-content").appendChild(d);
    const q = hex(getComputedStyle(d.querySelector(".callout-title")).color); d.remove();
    return {notice: [hex(n.color), hex(n.backgroundColor)], quote: q}') \
    || ag_die "cannot read the notice / quote callout colours"
ag_log "notice text/background, quote callout: $HARD"
python3 -I - "$AG_REPO" "$HARD" "$(cssvar text-muted)" <<'PY' || ag_die "notice text or quote callout colour wrong ($HARD)"
import json, sys
sys.path.insert(0, sys.argv[1])
from appglass import core
h = json.loads(sys.argv[2])
ok = core.contrast(*h["notice"]) >= 2.25 and h["quote"] == sys.argv[3]
sys.exit(0 if ok else 1)
PY

# 4. measure
args=(--content "$CONTENT8" --tol 6 --bar "$BAR8" --bar-tol 8)
for c in "${TEXTS[@]}"; do args+=(--text "$c"); done
WP=$(ag_wallpaper); [ -n "$WP" ] && args+=(--wallpaper "$WP")
MEASURE_RC=0
ag_measure "$AG_OUT/main-run$RUN.png" "${args[@]}" --json "$AG_OUT/measure-run$RUN.json" > /dev/null \
    || MEASURE_RC=$?

REGIONS_RC=0
python3 -I - "$AG_OUT" "$RUN" "$CONTENT8" "$BAR8" > "$AG_OUT/regions-run$RUN.json" <<'PY' || REGIONS_RC=$?
import collections, json, subprocess, sys
out, run, c8, b8 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
want = {"content": (c8, 6), "header": (c8, 6), "ribbon": (b8, 8), "sidebar": (b8, 8),
        "tabbar": (b8, 8), "controls": (b8, 8), "statusbar": (b8, 8), "vaultbar": (b8, 8),
        "palette": (255, 0), "menu": (255, 0), "notice": (255, 0),
        "navoff": None}     # glyph region: its brightest pixels must be opaque
res, fails = {}, []
for tag in ("main", "palette", "menu", "notice"):
    png = "%s/%s-run%s.png" % (out, tag, run)
    with open("%s/%s-rects-%s.json" % (out, tag, run)) as f:
        rects = json.load(f)
    w, h = map(int, subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", png]).decode().split(","))
    data = subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", png,
                                    "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
    ox, oy = (w - rects["w"]) // 2, (h - rects["h"]) // 2
    for k, r in rects["r"].items():
        if not r or r[2] < 8 or r[3] < 8:
            fails.append("%s: element missing or empty" % k)
            continue
        x0, y0 = int(r[0]) + ox + 3, int(r[1]) + oy + 3
        x1, y1 = int(r[0] + r[2]) + ox - 3, int(r[1] + r[3]) + oy - 3
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
            fails.append("%s: rect %s outside the shot" % (k, r))
            continue
        c = collections.Counter(data[(y * w + x) * 4 + 3] for y in range(y0, y1) for x in range(x0, x1))
        if want[k] is None:
            top = max(c)
            res[k] = {"alpha_max": top, "px_255": c.get(255, 0)}
            if top != 255 or c.get(255, 0) < 4:
                fails.append("%s: glyph alpha max %d (%d px at 255), expected 255"
                             % (k, top, c.get(255, 0)))
            continue
        mode, n = c.most_common(1)[0]
        a, tol = want[k]
        res[k] = {"alpha_mode": mode, "share": round(n / sum(c.values()), 3), "expected": a}
        if abs(mode - a) > tol:
            fails.append("%s: alpha %d, expected %d+-%d" % (k, mode, a, tol))
print(json.dumps({"regions": res, "fails": fails}, indent=1))
sys.exit(1 if fails else 0)
PY

# 5. quit, remove
js QUIT 30 >/dev/null || ag_log "WARN: quit via the debug port failed"
for i in $(seq 1 50); do ag_harness windows "$NAME" | grep -q obsidian || break; sleep 0.2; done
cp "$VAULT/.obsidian/appearance.json" "$AG_OUT/appearance-at-quit-$RUN.json"
ag_appglass "$SB" remove || ag_die "remove failed"
H2=$(ob_hash "$SB" 2> "$AG_OUT/files-after-$RUN.txt")
REMOVE_OK=1
[ "$H2" = "$H0" ] || REMOVE_OK=0
[ -e "$CSS" ] && REMOVE_OK=0
ag_stop_all
[ "$(sockstat "$CLISOCK")" = "$CLI0" ] || ag_die "$CLISOCK changed"

python3 -I - "$AG_OUT/measure-run$RUN.json" "$AG_OUT/regions-run$RUN.json" "$REMOVE_OK" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
g = json.load(open(sys.argv[2]))
t = m.get("text", {})
print("content alpha mode %s (expected %s, share %.2f); bar px %s; regions %s; "
      "glyph px min %s; min contrast %s; remove byte-identical: %s"
      % (m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"],
         m.get("bar", {}).get("px"),
         ", ".join("%s=%s" % (k, v.get("alpha_mode", v.get("alpha_max")))
                   for k, v in g["regions"].items()),
         min(v["glyph_alpha255_px"] for v in t.values()) if t else None,
         m.get("min_text_contrast"), sys.argv[3] == "1"))
for f in m["fails"] + g["fails"]:
    print("  fail: " + f)
PY
[ "$MEASURE_RC" = 0 ] || ag_die "measurements failed (see $AG_OUT/measure-run$RUN.json)"
[ "$REGIONS_RC" = 0 ] || ag_die "region alphas wrong (see $AG_OUT/regions-run$RUN.json)"
[ "$REMOVE_OK" = 1 ] || ag_die "remove left the sandbox different ($H0 != $H2)"
echo "e2e obsidian run $RUN: PASS"
