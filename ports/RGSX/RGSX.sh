#!/bin/bash
# >>> RGSX-MACOS-BEGIN
# macOS: hand off to the self-bootstrapping launcher. Shell-agnostic (POSIX sh, bash 3.2, zsh): no arrays, no double-bracket tests.
if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
	# shellcheck disable=SC3028
	_rgsx_src="${BASH_SOURCE:-$0}"
	_rgsx_dir="$(cd "$(dirname "$_rgsx_src")" 2>/dev/null && pwd -L)"
	if [ -n "$_rgsx_dir" ]; then
		RGSX_LAUNCHER_PATH="$_rgsx_dir/$(basename "$_rgsx_src")"
		export RGSX_LAUNCHER_PATH
	fi
	# Resolve file-level symlinks to find the helper (BSD readlink has no -f). Capped: loops fall through to the dialog.
	_rgsx_real="$_rgsx_src"
	_rgsx_n=0
	_rgsx_ok=1
	while [ -L "$_rgsx_real" ]; do
		_rgsx_n=$((_rgsx_n + 1))
		if [ "$_rgsx_n" -gt 20 ]; then
			_rgsx_ok=0
			break
		fi
		_rgsx_ld="$(cd "$(dirname "$_rgsx_real")" 2>/dev/null && pwd -L)"
		_rgsx_t="$(readlink "$_rgsx_real" 2>/dev/null)"
		if [ -z "$_rgsx_t" ] || [ -z "$_rgsx_ld" ]; then
			_rgsx_ok=0
			break
		fi
		case "$_rgsx_t" in
			/*) _rgsx_real="$_rgsx_t" ;;
			*) _rgsx_real="$_rgsx_ld/$_rgsx_t" ;;
		esac
	done
	_rgsx_real_dir=""
	if [ "$_rgsx_ok" = 1 ]; then
		_rgsx_real_dir="$(cd "$(dirname "$_rgsx_real")" 2>/dev/null && pwd -P)"
	fi
	if [ -n "$_rgsx_real_dir" ] && [ -r "$_rgsx_real_dir/macos/rgsx-macos" ]; then
		exec /bin/bash "$_rgsx_real_dir/macos/rgsx-macos" "$@"
	fi
	echo "RGSX is incomplete: macos/rgsx-macos is missing. Re-copy the whole ports folder." >&2
	osascript -e 'display dialog "RGSX is incomplete: macos/rgsx-macos is missing. Re-copy the whole ports folder." buttons {"OK"} default button 1 with icon stop' >/dev/null 2>&1
	exit 1
fi
# <<< RGSX-MACOS-END
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}" || true
LOGFILE="${LOG_DIR}/launcher.log"

detect_platform() {
	if [[ -f /etc/rocknix-release || -f /etc/rocknix-os-release ]]; then
		echo rocknix
		return
	fi
	if [[ -r /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
		echo rpi
		return
	fi
	if [[ -f /etc/batocera-release ]] || command -v batocera-info >/dev/null 2>&1; then
		echo batocera
		return
	
	fi
	echo generic
}

PLATFORM="$(detect_platform)"
echo "[RGSX] Platform detected: ${PLATFORM}" >>"${LOGFILE}"

case "${PLATFORM}" in
	rocknix)
		# Source system profile to get entware environment (PYTHONPATH, PATH)
		if [[ -f /etc/profile ]]; then
			# shellcheck source=/dev/null
			source /etc/profile 2>/dev/null || true
		fi
		# Add entware site-packages if present
		for sp in /storage/.opt/lib/python*/site-packages; do
			if [[ -d "${sp}" ]]; then
				export PYTHONPATH="${sp}${PYTHONPATH:+:${PYTHONPATH}}"
				echo "[RGSX] PYTHONPATH extended: ${sp}" >>"${LOGFILE}"
				break
			fi
		done

		# Verify required Python modules on Rocknix (pygame, requests)
		if command -v python3 >/dev/null 2>&1; then
			missing=""
			for mod in pygame requests; do
				if ! python3 -c "import ${mod}" >/dev/null 2>&1; then
					missing+=" ${mod}"
				fi
			done

			if [[ -n "${missing// /}" ]]; then
				echo "[RGSX] Missing python modules:${missing}" >>"${LOGFILE}"
				# Try opkg for requests first (available in entware)
				if command -v opkg >/dev/null 2>&1; then
					if echo "${missing}" | grep -qw "requests"; then
						opkg update >/dev/null 2>&1 || true
						opkg install python3-requests >>"${LOGFILE}" 2>&1 || true
					fi
				fi

				# Install remaining via pip (prefer binary wheels)
				to_install=()
				for mod in ${missing}; do
					# recheck requests in case opkg installed it
					if [[ "${mod}" == "requests" ]]; then
						if python3 -c "import requests" >/dev/null 2>&1; then
							continue
						fi
					fi
					to_install+=("${mod}")
				done
				if [[ ${#to_install[@]} -gt 0 ]]; then
					echo "[RGSX] Installing python modules via pip: ${to_install[*]}" >>"${LOGFILE}"
					python3 -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >>"${LOGFILE}" 2>&1 || true
					if ! python3 -m pip install --disable-pip-version-check --prefer-binary "${to_install[@]}" >>"${LOGFILE}" 2>&1; then
						python3 -m pip install --disable-pip-version-check --only-binary :all: "${to_install[@]}" >>"${LOGFILE}" 2>&1 || true
					fi
				fi
			fi
		fi
		;;
	rpi|batocera)
		# RPi/Batocera: assume system Python and system libs are present
		;; 
	generic)
		;; 
esac

# Run the app from the script directory and capture stdout/stderr to log
cd "${SCRIPT_DIR}"
exec python3 __main__.py >>"${LOGFILE}" 2>&1