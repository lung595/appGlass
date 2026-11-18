#!/usr/bin/env bash
# e2e: Dux Files (dfiles) and Dux Calendar (dcal) glass in a nested niri.
#
#   APPGLASS_HARNESS=<harness.sh> [APPGLASS_E2E_OUT=<dir>] tests/e2e/dux.sh
#
# 1. generate appglass.kdl in a scratch sandbox, start the nested niri with
#    the global Glass blur rule + that rule file
# 2. sandbox = harness TMP; seed DMS settings/colours (copies), a home with a
#    few files for dfiles to list, an existing dankcal ui-settings.json with
#    a key of its own; snapshot; appglass apply --only dux (twice: idempotent)
# 3. dfiles (own instance: its single-instance lock is per Wayland display,
#    no bus) and then dcal (database in TMP, no HTTP, no tray, no bus):
#    shoot each window, measure the glass alpha, opaque text and contrast,
#    quit the app through its own socket
# 4. appglass remove; the sandbox is byte-identical to the snapshot (files the
#    apps wrote for themselves while running are left out of the comparison)

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
ag_require

NAME=dux-e2e-$$
RUN=${APPGLASS_E2E_RUN:-1}
RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

for c in dfiles dcal; do command -v "$c" >/dev/null || ag_die "$c not installed"; done

seed() {
    local r=$1
    ag_mkroot "$r"
    ag_seed_dms "$r"
    ag_seed_niri "$r"
    local typo
    typo=$(ag_real_cache)/dms/dms-typography.json
    [ -f "$typo" ] && cp -- "$typo" "$r/cache/dms/dms-typography.json"
    mkdir -p "$r/home/Documents" "$r/home/Music" "$r/home/Pictures" "$r/home/Projects"
    printf 'notes\n' > "$r/home/notes.txt"
    printf 'appglass e2e\n' > "$r/home/Documents/readme.txt"
    mkdir -p "$r/config/dankcal"
    printf '{\n  "themeMode": "auto"\n}\n' > "$r/config/dankcal/ui-settings.json"
}

# path -> sha256 of every file under the sandbox trees ag_tree_hash covers
snapshot() {
    python3 - "$1" <<'PY'
import hashlib, json, os, sys
root = sys.argv[1]
out = {}
for top in ("config", "data", "state", "home", "cache/dms"):
    for dp, dns, fns in os.walk(os.path.join(root, top)):
        out[os.path.relpath(dp, root) + "/"] = "dir"
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                out[rel] = "link:" + os.readlink(p)
            else:
                with open(p, "rb") as f:
                    out[rel] = hashlib.sha256(f.read()).hexdigest()
print(json.dumps(out, sort_keys=True))
PY
}

# 1. the rule file, generated outside the session
PRE=$(mktemp -d "$AG_OUT/pre.XXXX")
seed "$PRE"
ag_appglass "$PRE" apply --only dux --quiet || ag_die "pre-apply failed"
for id in 'dev\.duxlabs\.files' 'dev\.duxlabs\.calendar'; do
    grep -qF "$id" "$PRE/config/niri/appglass.kdl" || ag_die "no niri match for $id"
done
KDL=$(ag_extra_kdl "$PRE")
printf '%s\n' "$KDL" > "$AG_OUT/extra.kdl"

ag_start "$NAME" "$KDL"
SB=$AG_TMP
WL=$(sed -n 's/^WL=//p' "$(dirname "$SB")/$NAME.env")
[ -n "$WL" ] && [ "$WL" != "${WAYLAND_DISPLAY:-wayland-1}" ] || ag_die "bad nested display '$WL'"

# 2. sandbox in the harness TMP
seed "$SB"
S0=$(snapshot "$SB")
H0=$(ag_tree_hash "$SB")
DCAL_SET=$SB/config/dankcal/ui-settings.json
INO0=$(stat -c %i "$DCAL_SET")
ag_appglass "$SB" apply --only dux || ag_die "apply failed"
cmp -s "$PRE/config/niri/appglass.kdl" "$SB/config/niri/appglass.kdl" \
    || ag_die "appglass.kdl differs from the one the session was started with"
[ "$(stat -c %i "$DCAL_SET")" = "$INO0" ] || ag_die "dankcal ui-settings.json not written in place"
H1=$(ag_tree_hash "$SB")
[ "$H0" != "$H1" ] || ag_die "apply changed nothing"
ag_appglass "$SB" apply --only dux --quiet
[ "$(ag_tree_hash "$SB")" = "$H1" ] || ag_die "second apply is not idempotent"
S1=$(snapshot "$SB")

jqf() { jq -r "$2" "$SB/config/$1/ui-settings.json"; }
[ "$(jqf dankcal .themeMode)" = auto ] || ag_die "dankcal key of its own lost"
for app in dfiles dankcal; do
    for k in floatingWindowTransparency floatingWindowForegroundTransparency \
             floatingWindowForegroundLayers blurEnabled; do
        [ "$(jqf "$app" ".$k")" != null ] || ag_die "$app: $k missing"
    done
done
cp "$SB/config/dfiles/ui-settings.json" "$AG_OUT/dfiles-ui-settings-$RUN.json"
cp "$DCAL_SET" "$AG_OUT/dcal-ui-settings-$RUN.json"

# expected levels and colours
read -r EXP < <(python3 - "$SB" <<'PY'
import json, os, sys
r = sys.argv[1]
def load(*p):
    with open(os.path.join(r, *p)) as f:
        return json.load(f)
d = load("cache", "dms", "dms-colors.json")
roles = d["colors"][d.get("mode", "dark")]
out = {"roles": {k: roles[k] for k in ("surface", "surface_container", "surface_container_high",
                                       "on_surface", "on_surface_variant", "primary")}}
for app, cfg in (("dfiles", "dfiles"), ("dcal", "dankcal")):
    s = load("config", cfg, "ui-settings.json")
    w, f = s["floatingWindowTransparency"], s["floatingWindowForegroundTransparency"]
    out[app] = {"w": w, "f": f, "pane": round(1 - (1 - w) * (1 - f), 4)}
print(json.dumps(out))
PY
)
printf '%s\n' "$EXP" > "$AG_OUT/expected-$RUN.json"
j() { printf '%s' "$EXP" | jq -r "$1"; }
WP=$(ag_wallpaper)

# the nested instance's socket: <prefix>-<pid>.sock of a process that runs
# on the nested display (never the user's own instance)
nested_sock() {
    local prefix=$1 s pid
    for s in "$RT/$prefix"-*.sock; do
        [ -S "$s" ] || continue
        pid=${s##*/$prefix-}; pid=${pid%.sock}
        [[ $pid =~ ^[0-9]+$ ]] || continue
        tr '\0' '\n' 2>/dev/null < "/proc/$pid/environ" | grep -qx "WAYLAND_DISPLAY=$WL" \
            && { echo "$s"; return 0; }
    done
    return 1
}

# the runtime files of app instances that are not ours (the user's): must
# not change while the test runs
runtime_snapshot() {
    python3 - "$RT" "$WL" <<'PY'
import hashlib, os, re, sys
rt, wl = sys.argv[1], sys.argv[2]
def ours(pid):
    try:
        with open("/proc/%s/environ" % pid, "rb") as f:
            return ("WAYLAND_DISPLAY=" + wl).encode() in f.read().split(b"\0")
    except OSError:
        return False
out = []
for n in sorted(os.listdir(rt)):
    if not re.match(r"(dfiles|dankcal)", n):
        continue
    m = re.match(r"(?:dfiles|dankcal)-(\d+)\.", n)
    if m and ours(m.group(1)):
        continue
    p = os.path.join(rt, n)
    if os.path.isdir(p) and not os.path.islink(p):
        for dp, dns, fns in os.walk(p):
            dns.sort()
            out.append("D " + os.path.relpath(dp, rt))
            out.extend("F " + os.path.relpath(os.path.join(dp, f), rt) for f in sorted(fns))
    elif os.path.isfile(p) and not os.path.islink(p):
        with open(p, "rb") as f:
            out.append("F %s %s" % (n, hashlib.sha256(f.read()).hexdigest()))
    else:
        out.append("O " + n)
print("\n".join(out))
PY
}
RT0=$(runtime_snapshot)
printf '%s\n' "$RT0" > "$AG_OUT/runtime-before-$RUN.txt"

# Quickshell's instance records, $RT/quickshell/{by-pid,by-id,by-shell/<h>,
# by-path}: our instances add some there. Names and link mtimes only (the
# user's shells write their logs all the time). clean: the new records of a
# dead instance on our display ($WL) that ran from a dfiles/dankcal unpack go,
# a by-path link the run touched gets its mtime back; prints the records
# of our display still there
qs_records() {   # list | clean <before.json>
    python3 - "$RT" "$WL" "$@" <<'PY'
import json, os, re, shutil, sys
rt, wl, mode = sys.argv[1:4]
q = os.path.join(rt, "quickshell")
def ls(d):
    try:
        return sorted(os.listdir(d))
    except OSError:
        return []
def names():
    out = {}
    for sub in ("by-pid", "by-id", "by-path", "by-shell"):
        for n in ls(os.path.join(q, sub)):
            p = os.path.join(q, sub, n)
            try:
                out[sub + "/" + n] = os.lstat(p).st_mtime_ns
            except OSError:
                continue
            if sub == "by-shell" and os.path.isdir(p) and not os.path.islink(p):
                for i in ls(p):
                    out["%s/%s/%s" % (sub, n, i)] = 0
    return out
if mode == "list":
    print(json.dumps(names()))
    sys.exit(0)
with open(sys.argv[4]) as f:
    before = json.load(f)
new = set(names()) - set(before)
shell = re.compile(re.escape(rt) + r"/(dfiles|dankcal)-shell/")
display = re.compile(r"(?<![\w-])%s(?![\w])" % re.escape(wl))
gone = set()
for k in sorted(new):
    pid = k[len("by-pid/"):] if k.startswith("by-pid/") else ""
    if not pid.isdigit() or os.path.exists("/proc/" + pid):
        continue
    link = os.path.join(q, k)
    iid = os.path.basename(os.readlink(link)) if os.path.islink(link) else ""
    if not iid or "by-id/" + iid not in new:
        continue
    try:
        with open(os.path.join(q, "by-id", iid, "instance.lock"), "rb") as f:
            lock = f.read().replace(b"\0", b"").decode("latin-1")
    except OSError:
        continue
    if not (shell.search(lock) and display.search(lock)):
        continue
    os.unlink(link)
    shutil.rmtree(os.path.join(q, "by-id", iid))
    gone.add(iid)
    print("e2e: runtime: removed our quickshell record %s (pid %s)" % (iid, pid), file=sys.stderr)
for k in sorted(new):
    parts = k.split("/")
    if len(parts) == 3 and parts[0] == "by-shell" and parts[2] in gone:
        os.unlink(os.path.join(q, k))
for k in sorted(new):
    parts = k.split("/")
    if len(parts) == 2 and parts[0] == "by-shell":
        try:
            os.rmdir(os.path.join(q, k))
        except OSError:
            pass
for k in sorted(new):
    p = os.path.join(q, k)
    if k.startswith("by-path/") and os.path.islink(p) and not os.path.exists(p):
        os.unlink(p)     # its by-shell dir went with our records
for k, t in before.items():
    p = os.path.join(q, k)
    if k.startswith("by-path/") and os.path.islink(p) and os.lstat(p).st_mtime_ns != t:
        os.utime(p, ns=(t, t), follow_symlinks=False)
# still new and on our display (a shell the user starts meanwhile is not ours)
for k in sorted(set(names()) - set(before)):
    if not k.startswith("by-id/"):
        continue
    try:
        with open(os.path.join(q, k, "instance.lock"), "rb") as f:
            lock = f.read().replace(b"\0", b"").decode("latin-1")
    except OSError:
        lock = ""
    if display.search(lock):
        print(k)
PY
}
QS0=$AG_OUT/quickshell-before-$RUN.json
qs_records list > "$QS0"

# the Quickshell copies our instances unpacked ($RT/<app>-shell/<id>, read-only
# dirs): those not there before the run and that no live process runs from
# (qs -p <dir>) are ours, and go; a shell parent made by the run goes once empty
# shell_in_use <dir>: a live process names it in its command line (the dir
# goes through the environment: an argument would name it in our own)
shell_in_use() {
    AG_SHELL_DIR=$1 python3 -I -c '
import glob, os, sys
d = os.environ["AG_SHELL_DIR"].encode()
for p in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        args = open(p, "rb").read().split(b"\0")
    except OSError:
        continue
    if any(a == d or a.startswith(d + b"/") for a in args):
        sys.exit(0)
sys.exit(1)'
}
drop_own_shells() {
    local app d id
    for app in dfiles dankcal; do
        [ -d "$RT/$app-shell" ] && [ ! -L "$RT/$app-shell" ] || continue
        for d in "$RT/$app-shell"/*/; do
            d=${d%/}; id=${d##*/}
            [ -d "$d" ] && [ ! -L "$d" ] || continue
            printf '%s\n' "$RT0" | grep -qxF "D $app-shell/$id" && continue
            if shell_in_use "$d"; then
                ag_log "runtime: $d in use, kept"
                continue
            fi
            chmod -R u+w -- "$d" && rm -rf -- "$d" && ag_log "runtime: removed our $app-shell/$id"
        done
        printf '%s\n' "$RT0" | grep -qxF "D $app-shell" \
            || rmdir -- "$RT/$app-shell" 2>/dev/null || true
    done
}

# dimmed out-of-month day digits of dcal (on_surface at 0.38 on the pane):
# their glyph cores sit at one alpha between the pane and 255; their
# contrast against the pane glass over white, black and the wallpaper
dim_check() {
    python3 - "$@" <<'PY'
import collections, json, subprocess, sys
shot, fg_hex, pane, wp, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]
def decode(path, size=None):
    if size is None:
        w, h = map(int, subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0", path]).decode().split(","))
        return subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path, "-f",
                                        "rawvideo", "-pix_fmt", "rgba", "-"]), (w, h)
    w, h = size
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,gblur=sigma=20"
          % (w, h, w, h))
    return subprocess.check_output(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", vf,
                                    "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                    "-"]), (w, h)
def lum(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])
def ratio(a, b):
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)
data, (w, h) = decode(shot)
fg = tuple(int(fg_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
pa = int(round(pane * 255))
hist = collections.Counter(data[3::4])
# the glass under the digits: the out-of-month cell layer (the largest fill
# above the pane alpha), else the pane itself
cells = {k: v for k, v in hist.items() if pa + 4 < k < 250 and v >= 2000}
ba = max(cells, key=cells.get) if cells else pa
gp = [i for i in range(3, len(data), 4) if data[i] == ba]
glass = [sorted(data[i - 3 + c] for i in gp)[len(gp) // 2] for c in range(3)] if gp else None
# dim glyph cores: alpha 0.38 + 0.62 * glass, premultiplied rgb 0.38 fg + 0.62 glass
exp = 0.38 * 255 + 0.62 * ba
rep = {"pane_alpha": pa, "glass_alpha": ba, "expected_alpha": round(exp), "fails": []}
px = []
if glass is not None:
    want = [0.38 * fg[c] + 0.62 * glass[c] for c in range(3)]
    for i in range(3, len(data), 4):
        if abs(data[i] - exp) <= 4 and all(abs(data[i - 3 + c] - want[c]) <= 10 for c in range(3)):
            px.append(i)
peak = collections.Counter(data[i] for i in px).most_common(1)[0][0] if px else None
px = [i for i in px if data[i] == peak]
rep["alpha"] = peak
rep["px"] = len(px)
if len(px) < 12:
    rep["fails"].append("dim digits: %d glyph px at alpha %s" % (len(px), peak))
else:
    backs = {"white": [(255, 255, 255)], "black": [(0, 0, 0)]}
    if wp:
        wd, _ = decode(wp, (w, h))
        backs["wallpaper"] = [tuple(wd[(j // 4) * 3:(j // 4) * 3 + 3]) for j in px[::5]]
    t = [sorted(data[i - 3 + c] for i in px)[len(px) // 2] for c in range(3)]
    ta, ga = peak / 255.0, ba / 255.0
    worst = {}
    for name, bs in backs.items():
        cs = []
        for b in bs:
            lt = lum([min(255, t[c] + b[c] * (1 - ta)) for c in range(3)])
            lg = lum([min(255, glass[c] + b[c] * (1 - ga)) for c in range(3)])
            cs.append(ratio(lt, lg))
        worst[name] = round(min(cs), 3)
    rep["contrast"] = worst
    rep["min_contrast"] = min(worst.values())
    if rep["min_contrast"] < 2.0:
        rep["fails"].append("dim digits %.2f:1 (< 2)" % rep["min_contrast"])
rep["pass"] = not rep["fails"]
with open(out, "w") as f:
    json.dump(rep, f, indent=1)
print(json.dumps(rep))
sys.exit(0 if rep["pass"] else 1)
PY
}

# quit an app through its own socket (never the user's instance), wait for it
quit_app() {
    local bin=$1 prefix=$2 var=$3 re=$4 sock i
    if sock=$(nested_sock "$prefix"); then
        env DBUS_SESSION_BUS_ADDRESS="unix:path=$SB/nobus" "$var=$sock" \
            timeout 10 "$bin" ipc ui.quit >/dev/null 2>&1 || true
    else
        ag_log "$bin: no socket for $WL, leaving it to harness stop"
    fi
    wait_gone "$re" || ag_log "$bin window still open after ui.quit"
}

wait_gone() {
    local re=$1 i
    for i in $(seq 1 50); do
        ag_harness windows "$NAME" 2>/dev/null | jq -e --arg re "$re" \
            'select(.app_id != null and (.app_id | test($re)))' >/dev/null || return 0
        sleep 0.2
    done
    return 1
}

# dfiles: a clean exit (ui.quit, SIGTERM) deletes the shared
# $XDG_RUNTIME_DIR/dfiles.path that the user's own instance wrote. So the
# nested instance is killed hard and only its own pid/sock/session/start
# files are removed afterwards.
stop_dfiles() {
    local sock pid f
    sock=$(nested_sock dfiles) || { ag_log "dfiles: no instance for $WL"; return 0; }
    pid=${sock##*/dfiles-}; pid=${pid%.sock}
    tr '\0' '\n' < "/proc/$pid/environ" | grep -qx "WAYLAND_DISPLAY=$WL" || return 0
    [ "$(cat "$RT/dfiles-$pid.session" 2>/dev/null)" = "$WL" ] \
        || FAILS+=("dfiles-$pid.session does not name $WL")
    # its UI child (qs) too, also hard: the shell unpack dir is shared
    local kids k
    kids=$(pgrep -P "$pid" || true)
    kill -KILL "$pid" 2>/dev/null || true
    for k in $kids; do
        tr '\0' '\n' < "/proc/$k/environ" 2>/dev/null | grep -qx "WAYLAND_DISPLAY=$WL" \
            && kill -KILL "$k" 2>/dev/null || true
    done
    for _ in $(seq 1 50); do [ -d "/proc/$pid" ] || break; sleep 0.1; done
    [ -d "/proc/$pid" ] && { ag_log "dfiles $pid still alive"; return 0; }
    for f in pid session sock start; do rm -f -- "$RT/dfiles-$pid.$f"; done
    wait_gone '^dev\.duxlabs\.files$' || ag_log "dfiles window still open after kill"
}

FAILS=()

# measure.py on one shot, with the text roles that must be opaque
measure() {
    local tag=$1 shot=$2; shift 2
    local args=("$@")
    [ -n "$WP" ] && args+=(--wallpaper "$WP")
    if ! ag_measure "$shot" "${args[@]}" --json "$AG_OUT/measure-$tag-$RUN.json" > /dev/null; then
        FAILS+=("$tag: $(jq -r '.fails | join("; ")' "$AG_OUT/measure-$tag-$RUN.json")")
    fi
}

# 3a. Dux Files
DPATH=$RT/dfiles.path
DPATH_SAVE=
if [ -f "$DPATH" ] && [ ! -L "$DPATH" ]; then
    DPATH_SAVE=$AG_OUT/dfiles.path.orig-$RUN
    cp -p -- "$DPATH" "$DPATH_SAVE"
fi
# on any exit: the nested dfiles goes first (hard), then the sessions
dux_cleanup() {
    local rc=$?
    stop_dfiles || true
    drop_own_shells || true
    if [ -n "$DPATH_SAVE" ] && [ ! -e "$DPATH" ]; then
        cp -p -- "$DPATH_SAVE" "$DPATH" && ag_log "restored $DPATH" || true
    fi
    ag_stop_all
    exit $rc
}
trap dux_cleanup EXIT
ag_run "$NAME" dfiles run >&2
ID=$(ag_wait_window "$NAME" '^dev\.duxlabs\.files$' 30) \
    || { tail -n 40 "$SB/app.log" >&2 || true; ag_die "no dfiles window"; }
sleep 3
SHOT_F=$AG_OUT/dfiles-run$RUN.png
ag_harness shot "$NAME" "$SHOT_F" "$ID" >&2
sock=$(nested_sock dfiles) && ag_log "dfiles: own instance $sock" \
    || FAILS+=("dfiles: no instance of its own for $WL")
# config A: one level, panes at the window alpha; names (on_surface) and the
# column header (primary) are opaque
measure dfiles "$SHOT_F" --content "$(j .dfiles.pane)" --tol 6 \
    --text "$(j .roles.on_surface)" --text "$(j .roles.primary)"
stop_dfiles

# 3b. Dux Calendar
ag_run "$NAME" env DANKCAL_DB_PATH="$SB/dcal.db" DANKCAL_DISABLE_HTTP=1 \
    DANKCAL_NO_TRAY=1 dcal run >&2
ID=$(ag_wait_window "$NAME" '^dev\.duxlabs\.calendar$' 30) \
    || { tail -n 40 "$SB/app.log" >&2 || true; ag_die "no dcal window"; }
sleep 3
SHOT_C=$AG_OUT/dcal-run$RUN.png
ag_harness shot "$NAME" "$SHOT_C" "$ID" >&2
# config B: title strip at the window alpha (the "bar"), toolbar and month
# grid at the stacked pane alpha; day digits and the title are opaque
measure dcal "$SHOT_C" --content "$(j .dcal.pane)" --tol 6 --bar "$(j .dcal.w)" --bar-tol 8 \
    --text "$(j .roles.on_surface)"
# the dimmed out-of-month digits (on_surface at 0.38 by design)
dim_check "$SHOT_C" "$(j .roles.on_surface)" "$(j .dcal.pane)" "$WP" \
    "$AG_OUT/dim-dcal-$RUN.json" > /dev/null || FAILS+=("dcal dim digits: $(jq -r '.fails | join("; ")' "$AG_OUT/dim-dcal-$RUN.json")")
quit_app dcal dankcal DANKCAL_SOCKET '^dev\.duxlabs\.calendar$'
sleep 1

# 4. remove. The apps may write files of their own (bookmarks, session
# state); those are not appglass's and are left out of the comparison. The
# files appglass merged into must be as the apps left them before remove.
S2=$(snapshot "$SB")
ag_appglass "$SB" remove || ag_die "remove failed"
S3=$(snapshot "$SB")
ag_stop_all
read -r REMOVE_REPORT < <(python3 - "$S0" "$S1" "$S2" "$S3" <<'PY'
import json, sys
s0, s1, s2, s3 = (json.loads(a) for a in sys.argv[1:5])
app_own = {p for p in s2 if p not in s1 or (s2[p] != s1[p] and "ui-settings.json" not in p)}
rewritten = [p for p in s1 if "ui-settings.json" in p and s2.get(p) != s1[p]]
diff = sorted(p for p in set(s0) | set(s3) if p not in app_own and s0.get(p) != s3.get(p))
print(json.dumps({"ok": not diff, "diff": diff, "app_own": sorted(app_own),
                  "app_rewrote_settings": rewritten}))
PY
)
printf '%s\n' "$REMOVE_REPORT" > "$AG_OUT/remove-$RUN.json"
[ "$(printf '%s' "$REMOVE_REPORT" | jq -r .ok)" = true ] \
    || FAILS+=("remove left differences: $(printf '%s' "$REMOVE_REPORT" | jq -c .diff)")
# the user's instances' runtime files are untouched; new ones (ours) noted
if [ -n "$DPATH_SAVE" ] && ! cmp -s "$DPATH_SAVE" "$DPATH"; then
    FAILS+=("dfiles.path of the user's instance changed or deleted (restored)")
    [ -e "$DPATH" ] || cp -p -- "$DPATH_SAVE" "$DPATH"
fi
drop_own_shells
QS_NEW=$(qs_records clean "$QS0")
[ -z "$QS_NEW" ] || FAILS+=("runtime: quickshell records left behind: $(echo $QS_NEW)")
RT1=$(runtime_snapshot)
printf '%s\n' "$RT1" > "$AG_OUT/runtime-after-$RUN.txt"
RT_LOST=$(comm -23 <(printf '%s\n' "$RT0" | sort) <(printf '%s\n' "$RT1" | sort) | grep -v '^$' || true)
RT_NEW=$(comm -13 <(printf '%s\n' "$RT0" | sort) <(printf '%s\n' "$RT1" | sort) | grep -v '^$' || true)
[ -z "$RT_LOST" ] || FAILS+=("runtime files of other instances changed: $(echo $RT_LOST)")
if [ -z "$RT_NEW" ]; then
    ag_log "runtime: nothing left behind"
else
    FAILS+=("runtime: left behind: $(printf '%s\n' "$RT_NEW" | head -n 5 | tr '\n' ' ')($(printf '%s\n' "$RT_NEW" | wc -l) entries)")
fi

for tag in dfiles dcal; do
    f=$AG_OUT/measure-$tag-$RUN.json
    [ -f "$f" ] && python3 - "$f" "$tag" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
t = m.get("text", {})
bar = m.get("bar")
print("%s: alpha mode %s (expected %s, share %.2f)%s; glyph px at 255 min %s; min contrast %s"
      % (sys.argv[2], m["content"]["alpha_mode"], m["content"]["expected"],
         m["content"]["share_within_tol"],
         "; bar %s px at %s" % (bar["px"], bar["expected"]) if bar else "",
         min(v["glyph_alpha255_px"] for v in t.values()) if t else None,
         m.get("min_text_contrast")))
PY
done
[ -f "$AG_OUT/dim-dcal-$RUN.json" ] && jq -r '"dcal dim digits: \(.px) px, alpha \(.alpha), worst contrast \(.min_contrast)"' "$AG_OUT/dim-dcal-$RUN.json"
printf '%s' "$REMOVE_REPORT" | jq -r '"remove byte-identical: \(.ok) (app files left out: \(.app_own | length), app rewrote settings: \(.app_rewrote_settings))"'

if [ "${#FAILS[@]}" -gt 0 ]; then
    for f in "${FAILS[@]}"; do echo "  fail: $f"; done
    ag_die "dux run $RUN"
fi
echo "e2e dux run $RUN: PASS"
