#!/bin/bash
# Clean-machine acceptance run for the macOS port. Opt-in (needs internet, downloads ~60 MB): RGSX_E2E=1 tests/e2e_clean_machine.sh
# Never touches the real ~/ROMs or ~/ES-DE: everything lives in a temp dir that is removed at the end.
# Launches the ES-DE-style launcher under /bin/zsh, /bin/sh and /bin/bash with a stock PATH (no brew, system python3.9).
set -u
if [ "${RGSX_E2E:-0}" != 1 ]; then
	echo "Set RGSX_E2E=1 to run (network + ~60 MB download)."
	exit 0
fi
R="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
FAILS=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }

mkdir -p "$T/home" "$T/tmp" "$T/ROMs/ports"
# shippable content only: no .DS_Store/__pycache__/logs/windows+linux binaries
rsync -a --exclude='.DS_Store' --exclude='__pycache__' --exclude='logs' --exclude='*.pyc' \
	--exclude='assets/progs/*.exe' --exclude='assets/progs/*.dll' --exclude='assets/progs/*_linux' \
	--exclude='assets/progs/7zz' --exclude='assets/progs/qbittorrent-*' --exclude='assets/progs/xdvdfs' \
	--exclude='assets/progs/custom_dns' --exclude='assets/progs/versionclean' \
	"$R/ports/" "$T/ROMs/ports/"
LAUNCHER="$T/ROMs/ports/RGSX/RGSX.sh"
HOME_DIR="$T/home"
CFGDIR="$HOME_DIR/Library/Application Support/RGSX"
RUNTIME="$CFGDIR/runtime"
echo "temp tree: $T"
echo "system python on stock PATH: $(PATH=/usr/bin:/bin:/usr/sbin:/sbin python3 --version 2>&1); brew on PATH: $(PATH=/usr/bin:/bin:/usr/sbin:/sbin command -v brew || echo no)"
echo "host: macOS $(sw_vers -productVersion) $(uname -m)"

# launch <shell> <label> <wait_for_bootstrap_seconds>: start launcher, wait for the app to start, let it run 30 s
launch() {
	local sh_bin="$1" label="$2" start end pid i started=0 alive=0
	start=$(date +%s)
	env -i HOME="$HOME_DIR" TMPDIR="$T/tmp" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
		SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RGSX_PROGRESS=none \
		"$sh_bin" "$LAUNCHER" >"$T/$label.out" 2>&1 &
	pid=$!
	i=0
	while [ "$i" -lt 900 ]; do
		if grep -q "starting app" "$CFGDIR/logs/bootstrap.log" 2>/dev/null && [ "$(grep -c 'starting app' "$CFGDIR/logs/bootstrap.log")" -ge "$EXPECT_STARTS" ]; then
			started=1
			break
		fi
		kill -0 "$pid" 2>/dev/null || break
		sleep 1
		i=$((i + 1))
	done
	end=$(date +%s)
	echo "[$label] app start reached=$started after $((end - start)) s"
	if [ "$started" = 1 ]; then
		sleep 30
		kill -0 "$pid" 2>/dev/null && alive=1
		kill -9 "$pid" 2>/dev/null # SIGTERM only opens the app's "confirm exit" screen
		wait "$pid" 2>/dev/null
		pkill -9 -f "$T/home" 2>/dev/null # its web-server child
		[ "$alive" = 1 ] && ok "[$label] app still running after ~30 s" || bad "[$label] app exited early"
	else
		bad "[$label] bootstrap did not reach app start (see below)"
		tail -n 20 "$T/$label.out"
		tail -n 30 "$CFGDIR/logs/bootstrap.log" 2>/dev/null
	fi
	if grep -q Traceback "$T/$label.out" "$CFGDIR/logs/RGSX.log" 2>/dev/null; then
		bad "[$label] traceback found"
		grep -h -B2 -A8 Traceback "$T/$label.out" "$CFGDIR/logs/RGSX.log" | tail -n 30
	else
		ok "[$label] no traceback"
	fi
	LAST_SECONDS=$((end - start))
}

EXPECT_STARTS=1
launch /bin/zsh zsh-first
echo "first launch (fresh HOME, full bootstrap): ${LAST_SECONDS} s to app start"
[ -x "$RUNTIME/python/bin/python3" ] && ok "pinned python installed" || bad "python missing"
[ -x "$RUNTIME/bin/7zz" ] && ok "7zz installed" || bad "7zz missing"
"$RUNTIME/bin/7zz" i 2>/dev/null | grep -q Rar5 && ok "7zz lists Rar5" || bad "7zz Rar5"
"$RUNTIME/venv/bin/python" -c 'import pygame, requests, PIL, watchdog' >/dev/null 2>&1 && ok "core+optional deps import" || bad "deps import"
"$RUNTIME/venv/bin/python" -c 'import libtorrent; print("libtorrent", libtorrent.__version__)' && ok "import libtorrent" || bad "import libtorrent"
grep -h "ROMS_FOLDER=" "$CFGDIR/logs/RGSX.log" | tail -n 1
if grep -h "ROMS_FOLDER=" "$CFGDIR/logs/RGSX.log" | tail -n 1 | grep -q "ROMS_FOLDER=.*$T/ROMs (source: derived)"; then ok "ROMS_FOLDER derived to $T/ROMs"; else bad "ROMS_FOLDER not derived"; fi
grep -h "launch:" "$CFGDIR/logs/bootstrap.log" | tail -n 1

echo "--- stamps"
for f in "$RUNTIME"/state/*; do echo "$(basename "$f"): $(cat "$f")"; done

# second launch (sh), then bash: must be fast and download nothing
EXPECT_STARTS=2
launch /bin/sh sh-second
echo "second launch via /bin/sh: ${LAST_SECONDS} s to app start"
if [ "${LAST_SECONDS}" -le 8 ]; then ok "second launch fast (${LAST_SECONDS} s)"; else bad "second launch slow (${LAST_SECONDS} s)"; fi
# stage lines after the last "launch:" header must not contain "stage"
LAST_LAUNCH_LINE=$(grep -n "launch:" "$CFGDIR/logs/bootstrap.log" | tail -n 1 | cut -d: -f1)
if tail -n +"$LAST_LAUNCH_LINE" "$CFGDIR/logs/bootstrap.log" | grep -q "stage "; then bad "second launch re-ran a stage"; else ok "second launch idempotent (no stage ran)"; fi
EXPECT_STARTS=3
launch /bin/bash bash-third
echo "third launch via /bin/bash: ${LAST_SECONDS} s to app start"
LAST_LAUNCH_LINE=$(grep -n "launch:" "$CFGDIR/logs/bootstrap.log" | tail -n 1 | cut -d: -f1)
if tail -n +"$LAST_LAUNCH_LINE" "$CFGDIR/logs/bootstrap.log" | grep -q "stage "; then bad "third launch re-ran a stage"; else ok "third launch idempotent (no stage ran)"; fi

echo "--- selftest"
env -i HOME="$HOME_DIR" TMPDIR="$T/tmp" PATH=/usr/bin:/bin:/usr/sbin:/sbin SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
	RGSX_PROGRESS=none RGSX_SELFTEST=1 /bin/zsh "$LAUNCHER" 2>&1 | tail -n 15
env -i HOME="$HOME_DIR" TMPDIR="$T/tmp" PATH=/usr/bin:/bin:/usr/sbin:/sbin SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
	RGSX_PROGRESS=none RGSX_SELFTEST=1 /bin/zsh "$LAUNCHER" 2>&1 | grep -q "SELFTEST OK" && ok "selftest" || bad "selftest"

echo "--- offline re-run (curl replaced by a failing stub): must make zero network calls"
mkdir -p "$T/offline"
printf '#!/bin/bash\necho "curl $*" >>"%s"\nexit 6\n' "$T/offline.calls" >"$T/offline/curl"
chmod +x "$T/offline/curl"
env -i HOME="$HOME_DIR" TMPDIR="$T/tmp" PATH="$T/offline:/usr/bin:/bin:/usr/sbin:/sbin" RGSX_EXTRA_PATH="$T/offline" RGSX_PROGRESS=none \
	RGSX_BOOTSTRAP_ONLY=1 /bin/zsh "$LAUNCHER" 2>&1 | tail -n 2
[ ! -s "$T/offline.calls" ] && ok "offline re-run: zero curl calls" || bad "offline re-run called curl"

echo "RESULT: $FAILS failure(s)"
[ "$FAILS" = 0 ]
