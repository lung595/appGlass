#!/usr/bin/env bash
# appGlass e2e harness: nested niri, app launch, RGBA shot, composite, cleanup.
# Usage:
#   harness.sh start <name>            -> prints "NIRI_SOCKET=... WAYLAND=wayland-N TMP=<dir>"; state in $P/run/<name>.env
#   harness.sh run <name> -- cmd...    -> launch cmd in nested env (temp XDG dirs from TMP)
#   harness.sh windows <name>          -> niri msg windows (nested)
#   harness.sh shot <name> <out.png> [id]  -> screenshot-window RGBA
#   harness.sh comp <in.png> <outprefix>   -> outprefix.{wp,white,black}.png composites
#   harness.sh alpha <in.png>           -> min/mean/max alpha stats
#   harness.sh stop <name>             -> kill nested niri + clients, rm tmp
set -euo pipefail
P=${APPGLASS_HARNESS_STATE:-${XDG_CACHE_HOME:-$HOME/.cache}/appglass-harness}
R=$XDG_RUNTIME_DIR
mkdir -p "$P/run"
cmd=${1:?cmd}; shift
case "$cmd" in
start)
  n=${1:?name}; envf=$P/run/$n.env
  [ -f "$envf" ] && { echo "already running: $envf" >&2; exit 1; }
  tmp=$(mktemp -d "$P/run/$n.XXXX"); mkdir -p "$tmp"/{config,data,state,cache,home,shots}
  cfg=$tmp/niri.kdl
  cat > "$cfg" <<KDL
screenshot-path "$tmp/shots/%Y%m%d-%H%M%S.png"
hotkey-overlay {
    skip-at-startup
}
prefer-no-csd
animations {
    off
}
layout {
    gaps 0
    background-color "#ff00ff"
    focus-ring {
        off
    }
    border {
        off
    }
}
KDL
  [ -n "${EXTRA_KDL:-}" ] && printf '%s\n' "$EXTRA_KDL" >> "$cfg"
  niri validate -c "$cfg" >/dev/null 2>&1 || { niri validate -c "$cfg"; exit 1; }
  exec 9>"$P/run/.start.lock"; flock 9   # serialize socket diffing between parallel probes
  before=$(ls "$R" | sort)
  env -u NIRI_SOCKET setsid niri -c "$cfg" >"$tmp/niri.log" 2>&1 < /dev/null &
  pid=$!
  sock=""; wl=""
  for i in $(seq 1 100); do
    after=$(ls "$R" | sort)
    new=$(comm -13 <(echo "$before") <(echo "$after"))
    sock=$(echo "$new" | grep -E '^niri\.wayland-[0-9]+\..*\.sock$' | head -1 || true)
    wl=$(echo "$new" | grep -E '^wayland-[0-9]+$' | head -1 || true)
    [ -n "$sock" ] && [ -n "$wl" ] && break
    sleep 0.1
  done
  [ -z "$sock" ] && { echo "nested niri failed"; cat "$tmp/niri.log"; kill $pid 2>/dev/null; exit 1; }
  printf 'PID=%s\nSOCK=%s\nWL=%s\nTMP=%s\nCFG=%s\n' "$pid" "$R/$sock" "$wl" "$tmp" "$cfg" > "$envf"
  flock -u 9
  cat "$envf";;
run)
  n=${1:?name}; shift; [ "${1:-}" = "--" ] && shift
  . "$P/run/$n.env"
  case " $* " in *dbus-run-session*|*dbus-launch*|*dbus-daemon*|*XDG_RUNTIME_DIR=*) echo "REFUSED: private D-Bus / XDG_RUNTIME_DIR override clobbers the real $R/doc portal mount"; exit 1;; esac
  grep -qF " $R/doc " /proc/self/mountinfo || echo "WARN: real document portal mount missing at $R/doc" >&2
  NOHOME=${KEEP_HOME:-0}
  extra=()
  [ "$NOHOME" = 1 ] || extra+=(HOME="$TMP/home")
  # NOBUS=1: no session/system bus at all (missing socket) -> no portals, no single-instance handoff, no gsettings on the real dconf
  [ "${NOBUS:-0}" = 1 ] && extra+=(DBUS_SESSION_BUS_ADDRESS="unix:path=$TMP/nobus" DBUS_SYSTEM_BUS_ADDRESS="unix:path=$TMP/nobus" GSETTINGS_BACKEND=memory)
  env -u DISPLAY -u NIRI_SOCKET WAYLAND_DISPLAY="$WL" NIRI_SOCKET="$SOCK" \
    XDG_CONFIG_HOME="$TMP/config" XDG_DATA_HOME="$TMP/data" XDG_STATE_HOME="$TMP/state" XDG_CACHE_HOME="$TMP/cache" \
    "${extra[@]}" setsid "$@" >>"$TMP/app.log" 2>&1 < /dev/null &
  echo "launched pid $!";;
msg)
  n=${1:?name}; shift; . "$P/run/$n.env"; NIRI_SOCKET="$SOCK" niri msg "$@";;
windows)
  n=${1:?name}; . "$P/run/$n.env"; NIRI_SOCKET="$SOCK" niri msg -j windows | jq -c '.[]|{id,app_id,title}';;
shot)
  n=${1:?name}; out=${2:?out}; id=${3:-}; . "$P/run/$n.env"
  rm -f "$TMP"/shots/*.png
  if [ -n "$id" ]; then NIRI_SOCKET="$SOCK" niri msg action screenshot-window --id "$id" >/dev/null
  else NIRI_SOCKET="$SOCK" niri msg action screenshot-window >/dev/null; fi
  for i in $(seq 1 50); do f=$(ls "$TMP"/shots/*.png 2>/dev/null | head -1 || true); [ -n "$f" ] && break; sleep 0.1; done
  [ -z "$f" ] && { echo "no shot"; exit 1; }
  sleep 0.2; cp "$f" "$out"; echo "$out";;
comp)
  # niri screenshot-window PNGs hold PREMULTIPLIED rgb: unpremultiply (geq) then straight overlay.
  in=${1:?in}; pre=${2:?prefix}
  WP=${APPGLASS_WALLPAPER:-$(jq -r .wallpaperPath "$HOME/.local/state/dms/session.json")}
  read W H < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$in" | tr , ' ')
  UN="format=rgba,geq=r='if(alpha(X\,Y)\,min(255\,r(X\,Y)*255/alpha(X\,Y))\,0)':g='if(alpha(X\,Y)\,min(255\,g(X\,Y)*255/alpha(X\,Y))\,0)':b='if(alpha(X\,Y)\,min(255\,b(X\,Y)*255/alpha(X\,Y))\,0)':a='alpha(X\,Y)'"
  ffmpeg -loglevel error -y -i "$WP" -i "$in" -filter_complex "[1]$UN[u];[0]scale=$W:$H:force_original_aspect_ratio=increase,crop=$W:$H,gblur=sigma=20,format=rgba[bg];[bg][u]overlay=format=rgb" -frames:v 1 "$pre.wp.png"
  for c in white black; do
    ffmpeg -loglevel error -y -f lavfi -i "color=$c:s=${W}x${H}" -i "$in" -filter_complex "[1]$UN[u];[0][u]overlay=format=rgb" -frames:v 1 "$pre.$c.png"
  done
  echo "$pre.wp.png $pre.white.png $pre.black.png";;
alpha)
  in=${1:?in}
  ffmpeg -i "$in" -vf "alphaextract,format=gray,signalstats,metadata=mode=print:file=-" -f null - 2>/dev/null | grep -oE '(YMIN|YAVG|YMAX)=[0-9.]+' | tr '\n' ' '; echo;;
stop)
  n=${1:?name}; envf=$P/run/$n.env; [ -f "$envf" ] || { echo "not running"; exit 0; }
  . "$envf"; [ "$WL" = "${WAYLAND_DISPLAY:-wayland-1}" ] && { echo "refusing: WL is the real display"; exit 1; }
  # kill clients started in this nested session: WAYLAND_DISPLAY=<nested> or any env var pointing into $TMP
  # (catches D-Bus-activated helpers like xdg-document-portal/gvfsd-fuse spawned with XDG_RUNTIME_DIR in TMP)
  anc=" "; q=$$; while [ "$q" -gt 1 ] 2>/dev/null; do anc="$anc$q "; q=$(awk '/^PPid:/{print $2}' /proc/$q/status 2>/dev/null || echo 1); done
  for p in $(pgrep -u "$USER" || true); do
    case "$anc" in *" $p "*) continue;; esac; [ "$p" = "$PID" ] && continue
    e=$({ tr "\0" "\n" < /proc/$p/environ; } 2>/dev/null || true)
    a=$({ tr "\0" " " < /proc/$p/cmdline; } 2>/dev/null || true)
    if printf '%s\n' "$e" | grep -qx "WAYLAND_DISPLAY=$WL" || printf '%s\n%s\n' "$e" "$a" | grep -qF "$TMP"; then
      kill "$p" 2>/dev/null || true
    fi
  done
  kill "$PID" 2>/dev/null || true
  for i in $(seq 1 50); do kill -0 "$PID" 2>/dev/null || break; sleep 0.1; done
  kill -9 "$PID" 2>/dev/null || true
  sleep 0.5
  # unmount any FUSE/other mount left under TMP (deepest first); NEVER rm across a mount
  for i in 1 2 3; do
    mnts=$(awk -v t="$TMP" '$5==t || index($5, t"/")==1 {print $5}' /proc/self/mountinfo | sort -r)
    [ -z "$mnts" ] && break
    for m in $mnts; do fusermount3 -u -z "$m" 2>/dev/null || fusermount -u -z "$m" 2>/dev/null || true; done
    sleep 0.5
  done
  if awk -v t="$TMP" '$5==t || index($5, t"/")==1 {f=1} END{exit !f}' /proc/self/mountinfo; then
    echo "REFUSING rm: mounts still under $TMP:"; awk -v t="$TMP" 'index($5, t)==1 {print $5, $9}' /proc/self/mountinfo; exit 1
  fi
  rm -rf --one-file-system "$TMP" "$envf"
  # a nested niri killed hard leaves its wayland-N socket; the next start would
  # re-bind that name and miss it in the diff. Remove ONLY this session's own WL
  # socket (+ its .lock), never the real display's, only once its niri is gone
  # and nothing listens on / holds it (fail closed when ss or fuser is missing).
  if [ -n "$WL" ] && [ "$WL" != "${WAYLAND_DISPLAY:-wayland-1}" ] && [ -S "$R/$WL" ] \
     && ! kill -0 "$PID" 2>/dev/null && command -v ss >/dev/null && command -v fuser >/dev/null \
     && ! ss -xlp 2>/dev/null | grep -qF " $R/$WL " \
     && ! fuser -s "$R/$WL" "$R/$WL.lock" 2>/dev/null; then
    rm -f -- "$R/$WL" "$R/$WL.lock" && echo "removed stale socket $WL"
  fi
  ls "$R" | grep -qx "$WL" && echo "WARN socket $WL left" || echo "stopped $n";;
*) echo "unknown $cmd"; exit 2;;
esac
