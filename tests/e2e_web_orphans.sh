#!/bin/bash
# Headless end-to-end check that the RGSX web server never outlives the app (macOS). Opt-in: RGSX_E2E=1 tests/e2e_web_orphans.sh
# Runs the real app (SDL dummy drivers) from a throw-away HOME; never touches ~/ROMs, ~/ES-DE or ~/Library/Application Support/RGSX.
# E2E_APP=<folder> runs another app tree (e.g. an unfixed checkout) to reproduce the old behaviour; E2E_PY=<python>.
# Every scenario ends with a process/listener listing and kills whatever is left; leftovers are reported as failures.
# shellcheck disable=SC2009,SC2015  # ps|grep is deliberate (BSD pgrep -f differs); A && B || C is used for PASS/FAIL lines
set -u
if [ "${RGSX_E2E:-0}" != 1 ]; then
	echo "Set RGSX_E2E=1 to run (starts RGSX headless, uses local ports)."
	exit 0
fi
R="$(cd "$(dirname "$0")/.." && pwd)"
APPDIR="${E2E_APP:-$R/ports/RGSX}"
PY="${E2E_PY:-$R/.venv-macos-port/bin/python}"
T="$(mktemp -d)"
export HOME="$T/home"
CFG="$HOME/Library/Application Support/RGSX"
mkdir -p "$HOME" "$T/ROMs/ports"
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy RGSX_HEADLESS=1 RGSX_ROMS_DIR="$T/ROMs" RGSX_WEB_HOST=0.0.0.0
FAILS=0
PGIDS=""
N=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }

# kill_group <pgid>: SIGTERM the whole group, wait up to 5 s, then SIGKILL
kill_group() {
	local g="$1" i=0
	kill -CONT -- "-$g" 2>/dev/null
	kill -TERM -- "-$g" 2>/dev/null || return 0
	while [ "$i" -lt 50 ] && kill -0 -- "-$g" 2>/dev/null; do
		sleep 0.1
		i=$((i + 1))
	done
	kill -KILL -- "-$g" 2>/dev/null
	return 0
}
# web_pids: pids of RGSX web servers of the tree under test (the "--host" argument excludes look-alikes)
web_pids() { ps -axo pid=,command= | grep -F "$APPDIR/rgsx_web.py --host" | grep -v grep | awk '{print $1}'; }
LOOK=""
sweep() {
	local g p
	for g in $PGIDS; do kill_group "$g"; done
	PGIDS=""
	for p in $(web_pids) $LOOK; do
		kill -CONT "$p" 2>/dev/null
		kill -KILL "$p" 2>/dev/null
	done
	return 0
}
cleanup() {
	trap - EXIT INT TERM HUP
	sweep
	if [ "${E2E_KEEP:-0}" = 1 ]; then echo "kept: $T"; else rm -rf "$T"; fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM HUP

free_port() { "$PY" -c 'import socket;s=socket.socket();s.bind(("",0));print(s.getsockname()[1])'; }
# report <label>: record the process table and the listeners (this is the evidence the reviewer reads)
report() {
	echo "--- [$1] ps -axo pid,ppid,etime,command | grep -E 'rgsx_web|__main__|e2e_driver'"
	ps -axo pid,ppid,etime,command | grep -E 'rgsx_web|__main__|e2e_driver' | grep -v grep | grep -F -e e2e_driver.py -e "$APPDIR/"
	echo "--- [$1] lsof -nP -iTCP:$P1,$P2 -sTCP:LISTEN"
	lsof -nP -iTCP:"$P1,$P2" -sTCP:LISTEN 2>/dev/null || echo "(no listener on $P1/$P2)"
	return 0
}
# start_app <port>: launch the driver in its own session; sets APP_PID and TRIG
start_app() {
	local port="$1" i=0
	N=$((N + 1))
	TRIG="$T/trig.$N"
	mkdir -p "$TRIG"
	# the requested port lives in the settings file (RGSX_WEB_PORT would override the Settings-driven restart)
	mkdir -p "$CFG"
	printf '{"web_port": %s}\n' "$port" >"$CFG/rgsx_settings.json"
	E2E_APP="$APPDIR" E2E_TRIGGERS="$TRIG" \
		/usr/bin/perl -e 'use POSIX qw(setsid); setsid(); exec @ARGV or die "exec: $!"' "$PY" "$R/tests/e2e_driver.py" >"$T/app.$N.out" 2>&1 &
	APP_PID=$!
	PGIDS="$PGIDS $APP_PID"
	while [ "$i" -lt 300 ]; do
		[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 1 "http://127.0.0.1:$port/")" = 200 ] && return 0
		kill -0 "$APP_PID" 2>/dev/null || return 1
		sleep 0.2
		i=$((i + 1))
	done
	return 1
}
wait_exit() { # wait_exit <pid> <seconds>
	local i=0 max=$(($2 * 10))
	while [ "$i" -lt "$max" ] && kill -0 "$1" 2>/dev/null; do sleep 0.1; i=$((i + 1)); done
	! kill -0 "$1" 2>/dev/null
}
wait_no_web() { # wait_no_web <seconds>
	local i=0 max=$(($1 * 10))
	while [ "$i" -lt "$max" ] && [ -n "$(web_pids)" ]; do sleep 0.1; i=$((i + 1)); done
	[ -z "$(web_pids)" ]
}
trigger() { # trigger <name> <arg>: wait for the .done file
	local i=0
	echo "$2" >"$TRIG/$1"
	while [ "$i" -lt 800 ] && [ ! -f "$TRIG/$1.done" ]; do sleep 0.2; i=$((i + 1)); done
	cat "$TRIG/$1.done" 2>/dev/null
	echo
}
listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1; }
expect_clean() { # expect_clean <label> <ports...>: no server process, no listener on the ports
	local label="$1" p
	shift
	wait_no_web 5 && ok "$label: no rgsx_web.py process left" || bad "$label: rgsx_web.py still running: $(web_pids | tr '\n' ' ')"
	for p in "$@"; do
		[ -z "$(listening "$p")" ] && ok "$label: port $p released" || bad "$label: port $p still listening"
	done
	report "$label"
	sweep
}

echo "temp: $T  app: $APPDIR  python: $PY"
P1=$(free_port)
P2=$(free_port)
while [ "$P2" = "$P1" ]; do P2=$(free_port); done

echo "=== S1: start, the server answers"
if start_app "$P1"; then ok "S1: http://127.0.0.1:$P1/ answers 200"; else bad "S1: server did not answer (see $T/app.$N.out)"; tail -n 15 "$T/app.$N.out"; fi
report S1
[ "$(web_pids | wc -l | tr -d ' ')" = 1 ] && ok "S1: exactly one server" || bad "S1: server count $(web_pids | wc -l)"

echo "=== S2: live restart to another port through the Settings code path"
OLD1=$(web_pids)
trigger restart_port "$P2"
sleep 1
[ "$(web_pids | wc -l | tr -d ' ')" = 1 ] && ok "S2: exactly one server after restart" || bad "S2: server count $(web_pids | wc -l)"
[ -n "$(listening "$P2")" ] && [ -z "$(listening "$P1")" ] && ok "S2: listens on $P2 only" || bad "S2: listeners P1=$(listening "$P1") P2=$(listening "$P2")"
NEW=$(web_pids)
[ "$NEW" != "$OLD1" ] && ok "S2: new pid ($NEW) replaced old pid ($OLD1)" || bad "S2: same pid"
grep -q "\"pid\": $NEW" "$CFG/web_server.pid" && ok "S2: pid file points at $NEW" || bad "S2: pid file: $(cat "$CFG/web_server.pid" 2>/dev/null)"
report S2

echo "=== S2b: Quit menu > Restart RGSX (os.execl keeps the app pid) must not orphan the old server"
trigger execl x
sleep 6
i=0
while [ "$i" -lt 100 ] && [ "$(web_pids | wc -l | tr -d ' ')" != 1 ]; do sleep 0.3; i=$((i + 1)); done
sleep 2
[ "$(web_pids | wc -l | tr -d ' ')" = 1 ] && ok "S2b: exactly one server after execl restart" || bad "S2b: $(web_pids | wc -l) servers: $(web_pids | tr '\n' ' ')"
[ "$(web_pids | head -n 1)" != "$NEW" ] && ok "S2b: the old server was replaced" || bad "S2b: old server $NEW survived the restart"
report S2b

echo "=== S3: normal quit path (Quit menu > Quit RGSX)"
trigger quit x
wait_exit "$APP_PID" 20 && ok "S3: app exited" || bad "S3: app still running"
expect_clean S3 "$P1" "$P2"
[ ! -f "$CFG/web_server.pid" ] && ok "S3: pid file removed" || bad "S3: pid file remains"
grep -q "arrêté proprement" "$CFG/logs/RGSX.log" 2>/dev/null && ok "S3: 'arrêté proprement' logged" || echo "INFO: no 'arrêté proprement' line (old tree or other log path)"

echo "=== S3b: quit while a Settings restart is in flight"
start_app "$P1" || bad "S3b: start failed"
trigger race "$P2"
wait_exit "$APP_PID" 25 && ok "S3b: app exited" || bad "S3b: app still running"
expect_clean S3b "$P1" "$P2"

for SIG in TERM HUP; do
	echo "=== S4: kill -$SIG <app pid>"
	start_app "$P1" || bad "S4 $SIG: start failed"
	report "S4-$SIG-before"
	kill "-$SIG" "$APP_PID"
	wait_exit "$APP_PID" 15 && ok "S4: app exited after SIG$SIG" || bad "S4: app survived SIG$SIG"
	expect_clean "S4-$SIG" "$P1"
done

echo "=== S5a: kill -9 <app pid>: the child's watchdog stops the server"
start_app "$P1" || bad "S5a: start failed"
kill -9 "$APP_PID"
wait_no_web 8 && ok "S5a: server exited by itself within 8 s" || bad "S5a: server survived kill -9 of the app"
expect_clean S5a "$P1"

echo "=== S5b: kill -9 with the watchdog disabled (server SIGSTOPped): next start must stop the stale server"
start_app "$P1" || bad "S5b: start failed"
STALE=$(web_pids)
kill -STOP "$STALE"
kill -9 "$APP_PID"
sleep 1.5
[ "$(web_pids)" = "$STALE" ] && ok "S5b: stale server $STALE is still there (orphan)" || bad "S5b: precondition failed"
report S5b-orphan
start_app "$P1" || bad "S5b: second start failed"
sleep 1
[ "$(web_pids | wc -l | tr -d ' ')" = 1 ] && [ "$(web_pids)" != "$STALE" ] && ok "S5b: stale $STALE gone, exactly one server ($(web_pids))" || bad "S5b: servers: $(web_pids | tr '\n' ' ')"
[ -n "$(listening "$P1")" ] && ok "S5b: new server listens on the originally requested port $P1" || bad "S5b: nothing on $P1"
grep -h "Stale RGSX web server" "$CFG/logs/"*.log 2>/dev/null | tail -n 2
report S5b
kill "$APP_PID"
wait_exit "$APP_PID" 15
expect_clean S5b-end "$P1"

echo "=== S6: unrelated look-alike processes are never touched"
/bin/sh -c "'$PY' -c 'import time;time.sleep(90)' rgsx_web.py '$APPDIR/rgsx_web.py' >/dev/null 2>&1 &"
/bin/sh -c "/bin/sleep 90 >/dev/null 2>&1 &"
/bin/sh -c "'$PY' -c 'import time;time.sleep(90)' lookalike_$$ >/dev/null 2>&1 &"
sleep 0.5
LOOK=$(ps -axo pid=,command= | grep -E "time.sleep\(90\)|/bin/sleep 90" | grep -v grep | awk '{print $1}')
start_app "$P1" || bad "S6: start failed"
ALIVE=0
for p in $LOOK; do kill -0 "$p" 2>/dev/null && ALIVE=$((ALIVE + 1)); done
[ "$ALIVE" = "$(echo "$LOOK" | wc -l | tr -d ' ')" ] && ok "S6: all $ALIVE look-alikes still alive" || bad "S6: a look-alike was killed ($ALIVE alive of $LOOK)"
report S6
for p in $LOOK; do kill -KILL "$p" 2>/dev/null; done
kill "$APP_PID"
wait_exit "$APP_PID" 15
expect_clean S6-end "$P1"

echo "=== S7: nested ports/ports folder"
mkdir -p "$T/N/ROMs/ports/ports"
rsync -a --exclude='__pycache__' --exclude='assets/progs' "$R/ports/RGSX" "$T/N/ROMs/ports/ports/"
OUT=$(env -u RGSX_ROMS_DIR RGSX_LAUNCHER_PATH="$T/N/ROMs/ports/ports/RGSX/RGSX.sh" "$PY" -c "
import sys; sys.path.insert(0, '$T/N/ROMs/ports/ports/RGSX'); import config; print(config.ROMS_FOLDER, config.ROMS_FOLDER_SOURCE)" 2>&1)
echo "$OUT"
case "$OUT" in
*"nested ports folder detected"*"$T/N/ROMs derived") ok "S7: ROMs root = outermost parent, warning logged" ;;
*) bad "S7: unexpected: $OUT" ;;
esac

echo "=== final: nothing left"
sweep
LEFT=$(ps -axo pid,ppid,etime,command | grep -E 'rgsx_web|__main__|e2e_driver' | grep -v grep | grep -F -e e2e_driver.py -e "$APPDIR/")
[ -z "$LEFT" ] && ok "no rgsx_web/__main__ process left" || { bad "leftovers:"; echo "$LEFT"; }
echo "RESULT: $FAILS failure(s)"
[ "$FAILS" = 0 ]
