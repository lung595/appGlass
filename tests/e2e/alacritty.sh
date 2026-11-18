#!/usr/bin/env bash
# e2e: Alacritty glass in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/alacritty.sh
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file
# 2. sandbox = harness TMP; seed DMS settings/colours (copies) and an
#    alacritty.toml shaped like a DMS one; snapshot; appglass apply
# 3. run alacritty with a demo (default text, 16 colours, dim text, an
#    explicit-background statusline), shoot the window, measure:
#    glass alpha = content, glyphs opaque, statusline opaque, contrast >= 2:1
# 4. appglass remove; the sandbox is byte-identical to the snapshot

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=alacritty-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
APPID='^Alacritty$'

command -v alacritty >/dev/null || ag_die "alacritty not installed"

seed() {
    local r=$1
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
    ag_copy_in "$(ag_real_config)/alacritty/dank-theme.toml" "$AG_FIX/alacritty/dank-theme.toml" \
        "$r/config/alacritty/dank-theme.toml"
    # the user's layout, but HOME and XDG_CONFIG_HOME differ here: absolute import
    sed "s#\"~/.config/alacritty/dank-theme.toml\"#\"$r/config/alacritty/dank-theme.toml\"#" \
        "$AG_FIX/alacritty/alacritty.toml" > "$r/config/alacritty/alacritty.toml"
}

# 1. the rule file, generated outside the session
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
ag_appglass "$PRE" apply --only alacritty --quiet || ag_die "pre-apply failed"
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"

ag_start "$NAME" "$KDL"
SB=$AG_TMP

# 2. sandbox in the harness TMP
seed "$SB"
H0=$(ag_tree_hash "$SB")
ag_appglass "$SB" apply --only alacritty || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
grep -q "appglass.toml" "$SB/config/alacritty/alacritty.toml" || ag_die "import not added"
H1=$(ag_tree_hash "$SB")
[ "$H0" != "$H1" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only alacritty --quiet
[ "$(ag_tree_hash "$SB")" = "$H1" ] || ag_die "second apply is not idempotent"

# expected colours: dank-theme.toml, then appglass.toml (import order)
read -r EXP < <(python3 - "$SB" <<'PY'
import json, os, sys, tomllib
r = sys.argv[1]
c = {}
for n in ("dank-theme.toml", "appglass.toml"):
    with open(os.path.join(r, "config", "alacritty", n), "rb") as f:
        for sec, v in tomllib.load(f).get("colors", {}).items():
            if isinstance(v, dict):
                c.setdefault(sec, {}).update(v)
with open(os.path.join(r, "cache", "dms", "dms-colors.json")) as f:
    d = json.load(f)
mode = d.get("mode", "dark")
roles = d["colors"][mode]
with open(os.path.join(r, "config", "alacritty", "appglass.toml"), "rb") as f:
    op = tomllib.load(f)["window"]["opacity"]
names = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
out = {"fg": c["primary"]["foreground"], "dimfg": c["primary"].get("dim_foreground", ""),
       "normal": [c["normal"][n] for n in names], "bright": [c["bright"][n] for n in names],
       "dim": [c.get("dim", {}).get(n, "") for n in names],
       "bar_bg": roles["surface_container_high"], "bar_fg": roles["on_surface"],
       "opacity": op}
print(json.dumps(out))
PY
)
printf '%s\n' "$EXP" > "$AG_OUT/expected-$RUN.json"
j() { printf '%s' "$EXP" | jq -r "$1"; }
CONTENT=$(j .opacity)

# 3. the app
DEMO=$AG_OUT/demo.sh
python3 - "$EXP" > "$DEMO" <<'PY'
import json, sys
e = json.loads(sys.argv[1])
def rgb(h):
    h = h.lstrip("#"); return ";".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
L = ["#!/bin/sh", "printf '\\033[?25l'"]
L.append("printf 'appglass e2e: default text on the glass, The quick brown fox 0123456789 \\342\\226\\210\\342\\226\\210\\342\\226\\210\\n\\n'")
for sgr, label in (("3", "normal"), ("9", "bright"), ("2;3", "dim")):
    for i in range(8):
        L.append("printf '\\033[%s%dm%s%d \\342\\226\\210\\342\\226\\210\\342\\226\\210 \\033[0m'" % (sgr, i, label[0], i))
    L.append("echo")
L.append("printf '\\033[2mdim default text \\342\\226\\210\\342\\226\\210\\342\\226\\210\\033[0m\\n\\n'")
bar = "  NORMAL  main  statusline (explicit bg)"
L.append("printf '\\033[48;2;%sm\\033[38;2;%sm%-48s\\033[0m\\n'" % (rgb(e["bar_bg"]), rgb(e["bar_fg"]), bar))
L.append("printf '\\033[48;2;%sm\\033[38;2;%sm%-48s\\033[0m\\n'" % (rgb(e["bar_bg"]), rgb(e["bar_fg"]), "  second statusline row"))
L.append("exec sleep 600")
print("\n".join(L))
PY
chmod +x "$DEMO"
# its IPC socket in the sandbox, not the runtime dir (a killed alacritty
# leaves it behind)
ag_run "$NAME" alacritty --socket "$SB/alacritty.sock" -e "$DEMO" >&2
ID=$(ag_wait_window "$NAME" "$APPID" 20) || { cat "$SB/app.log" >&2 || true; ag_die "no Alacritty window"; }
sleep 2
SHOT=$AG_OUT/alacritty-run$RUN.png
ag_harness shot "$NAME" "$SHOT" "$ID" >&2

args=(--content "$CONTENT" --tol 6 --solid "$(j .bar_bg)" --text "$(j .fg)" --text "$(j .bar_fg)")
for k in normal bright dim; do
    for c in $(j ".$k[]"); do [ -n "$c" ] && args+=(--text "$c"); done
done
[ -n "$(j .dimfg)" ] && args+=(--text "$(j .dimfg)")
WP=$(ag_wallpaper); [ -n "$WP" ] && args+=(--wallpaper "$WP")
MEASURE_RC=0
ag_measure "$SHOT" "${args[@]}" --json "$AG_OUT/measure-run$RUN.json" > /dev/null || MEASURE_RC=$?

# 4. remove
ag_appglass "$SB" remove || ag_die "remove failed"
H2=$(ag_tree_hash "$SB")
REMOVE_OK=1
[ "$H2" = "$H0" ] || REMOVE_OK=0
ag_stop_all

python3 - "$AG_OUT/measure-run$RUN.json" "$REMOVE_OK" "$H0" "$H2" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
t = m.get("text", {})
print("content alpha mode %s (expected %s, share %.2f); opaque statusline px %s; "
      "glyph px min %s; min contrast %s; remove byte-identical: %s"
      % (m["content"]["alpha_mode"], m["content"]["expected"], m["content"]["share_within_tol"],
         list(m.get("solid", {}).values())[0]["alpha255_px"] if m.get("solid") else None,
         min(v["glyph_alpha255_px"] for v in t.values()) if t else None,
         m.get("min_text_contrast"), sys.argv[2] == "1"))
for f in m["fails"]:
    print("  fail: " + f)
PY
[ "$MEASURE_RC" = 0 ] || ag_die "measurements failed (see $AG_OUT/measure-run$RUN.json)"
[ "$REMOVE_OK" = 1 ] || ag_die "remove left the sandbox different ($H0 != $H2)"
echo "e2e alacritty run $RUN: PASS"
