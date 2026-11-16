#!/usr/bin/sh
# gen-css.sh <template> <out.css>: fill the Jellyfin glass CSS template from `appglass levels`
# and the DMS colours (~/.cache/dms/dms-colors.json). Falls back to 0.8 / built-in colours.
set -u
tmpl=$1; out=$2
COLORS="${XDG_CACHE_HOME:-$HOME/.cache}/dms/dms-colors.json"
lv=$("@APPGLASS@" levels 2>/dev/null) || lv=''
c=$(printf '%s' "$lv" | jq -r '.content // empty' 2>/dev/null); [ -n "$c" ] || c=0.8
b=$(printf '%s' "$lv" | jq -r '.bar_over_content // empty' 2>/dev/null); [ -n "$b" ] || b=0
mode=$(jq -r '.mode // "dark"' "$COLORS" 2>/dev/null) || mode=dark
rgb() {  # DMS colour key -> "r, g, b"
    h=$(jq -r --arg m "$mode" --arg k "$1" '.colors[$m][$k] // empty' "$COLORS" 2>/dev/null | tr -d '#')
    [ ${#h} -eq 6 ] || h=$2
    printf '%d, %d, %d' "0x$(echo $h | cut -c1-2)" "0x$(echo $h | cut -c3-4)" "0x$(echo $h | cut -c5-6)"
}
os=$(rgb on_surface e4e3d6)
sed -e "s/{{content}}/$c/g" -e "s/{{bar_over}}/$b/g" \
    -e "s/{{surface}}/$(rgb surface 13140d)/g" -e "s/{{surface_container}}/$(rgb surface_container 21221a)/g" \
    -e "s/{{surface_container_high}}/$(rgb surface_container_high 2b2c24)/g" \
    -e "s/{{on_surface}}/$os/g" -e "s/{{on_surface_rgb}}/$os/g" \
    -e "s/{{on_surface_variant}}/$(rgb on_surface_variant c7c7b7)/g" \
    "$tmpl" > "$out.tmp" && mv -f "$out.tmp" "$out"
