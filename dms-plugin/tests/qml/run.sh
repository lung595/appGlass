#!/bin/sh
# Runs the QML tests (tests/qml/*.test.qml) offscreen, without Quickshell or
# DMS: stubs/ stands in for Quickshell, Quickshell.Io and the qs.* modules
# (Proc records the commands instead of running them, ToastService the
# toasts, PluginService the saves...). Needs Qt 6's qml tool (qml6, qml-qt6
# or qml).
#
#   sh tests/qml/run.sh          every test
#   sh tests/qml/run.sh daemon   only the tests whose file name contains "daemon"
#
# A test passes when it exits 0, Harness.finish() printed its HARNESS-DONE
# line (so a test that quits on its own or checks nothing fails) AND the engine printed no
# warning, error or TypeError: QT_MESSAGE_PATTERN prefixes each line with its
# level, so print()/console.log lines read "debug qml: ...", and any
# "warning"/"critical"/"fatal" line fails the test. A test that never exits
# is killed after 120 s and fails.
#
# The tests run in a temporary copy that mirrors the plugin root (its QML,
# components/, plugin.json) with the tests and Harness.qml beside them, so a
# test names a plugin component directly (AppGlassDaemon { ... }) or imports
# "components". The CLI contract (what `appglass status --json` prints, the
# default settings.json) comes from the repository's tests/fixtures. HOME and the
# XDG folders point inside that copy: nothing is read or written in the real
# home, and the QML disk cache is off.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$(dirname "$here")")
repo=$(dirname "$root")
filter=${1:-}

qml=""
for tool in qml6 qml-qt6 qml /usr/lib64/qt6/bin/qml /usr/lib/qt6/bin/qml; do
    if command -v "$tool" >/dev/null 2>&1; then
        qml=$tool
        break
    fi
done
if [ -z "$qml" ]; then
    echo "run.sh: no Qt 6 qml tool found (qml6, qml-qt6 or qml)" >&2
    exit 2
fi

# The plugin's own QML must use the DMS 2 widgets (qs.DCommon.Widgets: the
# qs.Widgets Dank* shims log a deprecation error naming the plugin) and none
# of the stubs' test-only members (the _test prefix)
if grep -snE '\bDank(Button|Toggle|Icon|TextField|Slider)\b|\b_test[A-Za-z]' \
    "$root"/*.qml "$root"/components/*.qml "$root"/components/*.js \
    "$root"/components/settings/*.qml "$root"/components/settings/*.js; then
    echo "run.sh: the plugin QML above uses a deprecated Dank* widget or a test-only _test member" >&2
    exit 1
fi

work=$(mktemp -d "${TMPDIR:-/tmp}/ag-qmltest.XXXXXX")
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM

# The plugin root, without its tests, docs or media
for entry in "$root"/*.qml "$root"/*.js "$root"/*.json \
    "$root"/components "$root"/translations; do
    if [ -e "$entry" ]; then
        cp -R "$entry" "$work"/
    fi
done
# A second copy for reload.test.qml, which rewrites it in place (an update)
# and loads it again at the next revision, as DMS's plugin reload does
mkdir "$work/reload"
for entry in "$root"/*.qml "$root"/*.js "$root"/*.json "$root"/components; do
    if [ -e "$entry" ]; then
        cp -R "$entry" "$work/reload"/
    fi
done
# The tests and their helpers (Harness.qml...) beside it, and the CLI
# contract fixtures (Harness.readFile("contract/status.json"))
cp "$here"/*.qml "$work"/
mkdir "$work/contract"
cp "$repo/tests/fixtures/status/golden.json" "$work/contract/status.json"
cp "$repo/tests/fixtures/plugin/defaults.json" "$work/contract/defaults.json"

mkdir -p "$work/.home/.config" "$work/.home/.cache" "$work/.home/.local/state" "$work/.home/.local/share"
export HOME="$work/.home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_CACHE_HOME="$HOME/.cache"
export XDG_STATE_HOME="$HOME/.local/state" XDG_DATA_HOME="$HOME/.local/share"
export QML_DISABLE_DISK_CACHE=1
# Lets Harness.readFile() read the copy (plugin files, fixtures) with a
# synchronous file:// XMLHttpRequest
export QML_XHR_ALLOW_FILE_READ=1
# ... and reload.test.qml rewrite its copy (reload/, in the work folder)
export QML_XHR_ALLOW_FILE_WRITE=1
export QT_QPA_PLATFORM=offscreen
# Everything to the terminal (not journald), print() included, each line
# prefixed with its level
export QT_FORCE_STDERR_LOGGING=1
export QT_LOGGING_RULES='qml.debug=true;js.debug=true'
export QT_MESSAGE_PATTERN='%{type} %{if-category}%{category}: %{endif}%{message}'

out="$work/out.txt"
ran=0
failed=""
for test in "$work"/*.test.qml; do
    [ -e "$test" ] || continue
    name=${test##*/}
    case $name in *"$filter"*) ;; *) continue ;; esac
    ran=$((ran + 1))
    echo "=== $name"
    status=0
    # quickshell keeps the QML disk cache on, and a file it loads again with
    # "?revision=N" comes back from that cache with the URL it was first
    # compiled under: reload.test.qml needs the cache to see what DMS sees
    cache=""
    [ "$name" = reload.test.qml ] && cache="$work/qmlcache"
    (cd "$work" && if [ -n "$cache" ]; then
        env -u QML_DISABLE_DISK_CACHE QML_DISK_CACHE_PATH="$cache" timeout 120 "$qml" -I "$here/stubs" "$test"
    else
        timeout 120 "$qml" -I "$here/stubs" "$test"
    fi) >"$out" 2>&1 || status=$?
    cat "$out"
    reason=""
    if [ "$status" -ne 0 ]; then
        reason="exit status $status"
    elif grep -qE '^(warning|critical|fatal) ' "$out"; then
        reason="QML warnings or errors (listed above)"
    elif grep -vE '^(debug|info) ' "$out" | grep -qE 'Warning|TypeError|ReferenceError|Unable to assign|is not a function|is not a type|Binding loop|Cannot (read|call|assign)'; then
        reason="QML warnings or errors (listed above)"
    elif grep -qE '^(debug|info) qml: FAIL' "$out"; then
        reason="a check failed"
    elif ! grep -qE '^(debug|info) qml: HARNESS-DONE [1-9][0-9]* checks$' "$out"; then
        reason="no HARNESS-DONE line (the test must end with Harness.finish())"
    fi
    if [ -n "$reason" ]; then
        echo "FAIL $name: $reason"
        failed="$failed $name"
    else
        echo "PASS $name"
    fi
done

if [ "$ran" -eq 0 ]; then
    if [ -n "$filter" ]; then
        echo "run.sh: no test matches \"$filter\"" >&2
        exit 1
    fi
    echo "run.sh: no tests"
    exit 0
fi
if [ -n "$failed" ]; then
    echo "QML tests: $ran run, failed:$failed" >&2
    exit 1
fi
echo "QML tests: $ran run, all passed"
