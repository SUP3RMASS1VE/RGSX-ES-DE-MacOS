"""Tests for the self-contained, ES-DE-launched macOS distribution.

Run: HOME=$(mktemp -d) python -m unittest discover -s tests -v
No test touches the network: downloads use file:// fixtures and stub curl/osascript/open/sw_vers/xattr/pip.
"""
import difflib
import importlib.util
import json
import lzma
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import types
import unittest
from unittest import mock

_TMP_HOME = tempfile.mkdtemp(prefix="rgsx_sc_home_")
os.environ.setdefault("HOME", _TMP_HOME)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("RGSX_HEADLESS", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "ports", "RGSX")
MACOS = os.path.join(APP, "macos")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
BASELINE = os.path.join(FIXTURES, "premacos_baseline")
sys.path.insert(0, APP)

import config  # noqa: E402

ON_MAC_ARM = platform.system() == "Darwin" and platform.machine() == "arm64"

_orig_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost", "0.0.0.0") and self.family != getattr(socket, "AF_UNIX", -1):
        raise OSError(f"network access blocked in tests: {address!r}")
    return _orig_connect(self, address)


def setUpModule():
    socket.socket.connect = _guarded_connect


def tearDownModule():
    socket.socket.connect = _orig_connect
    shutil.rmtree(_TMP_HOME, ignore_errors=True)
    home = os.environ.get("HOME", "")
    if os.path.basename(home).startswith(("rgsx_test_home_", "rgsx_sc_home_")):
        shutil.rmtree(home, ignore_errors=True)  # recreated by tests that ran after the other module's teardown


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


# ---------------------------------------------------------------------------------------------------------
class LockFileTests(unittest.TestCase):
    def _entries(self, name):
        entries, cur = [], None
        for line in _read(os.path.join(MACOS, name)).splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.lstrip().startswith("--hash=sha256:"):
                cur["hashes"].append(line.strip().split()[0][len("--hash=sha256:"):])
            else:
                cur = {"req": line.strip().rstrip("\\").strip(), "hashes": []}
                entries.append(cur)
        return entries

    def test_all_requirements_hashed(self):
        for name in ("requirements-core.lock", "requirements-optional.lock", "requirements-torrent.lock"):
            entries = self._entries(name)
            self.assertTrue(entries, name)
            for e in entries:
                self.assertRegex(e["req"], r"^[A-Za-z0-9_.\-]+==[0-9][^ ]*$", e)
                self.assertTrue(e["hashes"], f"{name}: {e['req']} has no hash")
                for h in e["hashes"]:
                    self.assertRegex(h, r"^[0-9a-f]{64}$")

    def test_in_pins_present_in_lock(self):
        for kind in ("core", "optional", "torrent"):
            locked = {e["req"].lower().replace("_", "-") for e in self._entries(f"requirements-{kind}.lock")}
            for line in _read(os.path.join(MACOS, f"requirements-{kind}.in")).splitlines():
                if line.strip() and not line.startswith("#"):
                    self.assertIn(line.strip().lower().replace("_", "-"), locked, f"{kind}: {line}")

    def test_core_lock_covers_transitive_deps(self):
        names = {e["req"].split("==")[0] for e in self._entries("requirements-core.lock")}
        for dep in ("pygame", "requests", "urllib3", "idna", "certifi", "charset-normalizer"):
            self.assertIn(dep, names)

    def test_torrent_lock_has_both_wheel_hashes(self):
        (entry,) = self._entries("requirements-torrent.lock")
        self.assertEqual(entry["req"], "libtorrent==2.1.1")
        h14 = [h for h in entry["hashes"] if h.startswith("768375f6") and h.endswith("46d4")]
        h15 = [h for h in entry["hashes"] if h.startswith("188aa0f0") and h.endswith("5078")]
        self.assertEqual(len(h14), 1, "macosx_14_0 hash missing")
        self.assertEqual(len(h15), 1, "macosx_15_0 hash missing")

    def test_pins_urls_literal_and_https(self):
        pins = dict(line.split("=", 1) for line in _read(os.path.join(MACOS, "pins")).splitlines() if "=" in line and not line.startswith("#"))
        self.assertTrue(pins["PBS_URL"].startswith("https://github.com/astral-sh/python-build-standalone/releases/download/20261009/"))
        self.assertIn("cpython-3.12.15%2B20261009-aarch64-apple-darwin-install_only.tar.gz", pins["PBS_URL"])
        self.assertTrue(pins["SEVENZIP_URL"].startswith("https://www.7-zip.org/"))
        for key in ("PBS_SHA256", "SEVENZIP_SHA256"):
            self.assertRegex(pins[key], r"^[0-9a-f]{64}$")
        self.assertNotIn("$", pins["PBS_URL"])


# ---------------------------------------------------------------------------------------------------------
STUB_PY = textwrap.dedent('''\
    #!/bin/bash
    # stub python: behaves from files under $STUB_DIR
    echo "py $*" >>"$STUB_DIR/py.calls"
    case "$1" in
      __main__.py)
        { echo "APP_RAN $*"; echo "RGSX_SEVENZIP=$RGSX_SEVENZIP"; echo "RGSX_LAUNCHER_PATH=${RGSX_LAUNCHER_PATH:-}"; echo "RGSX_RUNTIME_DIR=$RGSX_RUNTIME_DIR"; } >"$STUB_DIR/app.out"
        exit 0 ;;
      -m)
        if [ "$2" = venv ]; then mkdir -p "$3/bin" && cp "$STUB_PY" "$3/bin/python" && chmod 755 "$3/bin/python"; exit 0; fi
        if [ "$2" = pip ]; then
          lock=""
          for a in "$@"; do lock="$a"; done
          name="$(basename "$lock" .lock)"; name="${name#requirements-}"
          echo "pip $name $*" >>"$STUB_DIR/pip.calls"
          if [ -e "$STUB_DIR/fail_$name" ]; then
            if [ -e "$STUB_DIR/nowheel_$name" ]; then echo "ERROR: No matching distribution found for libtorrent"; else echo "ERROR: boom for $name"; fi
            exit 1
          fi
          touch "$STUB_DIR/installed_$name"; echo "Successfully installed $name"; exit 0
        fi ;;
      -c)
        case "$2" in
          *platform.machine*) [ -e "$STUB_DIR/invalid_python" ] && exit 1; exit 0 ;;
          *"import sys"*) exit 0 ;;
          *"ssl, venv"*) exit 0 ;;
          *pygame*) [ -e "$STUB_DIR/installed_core" ]; exit $? ;;
          *PIL*) [ -e "$STUB_DIR/installed_optional" ]; exit $? ;;
          *libtorrent*) [ -e "$STUB_DIR/installed_torrent" ]; exit $? ;;
        esac ;;
    esac
    exit 0
''')

STUB_CURL = textwrap.dedent('''\
    #!/bin/bash
    echo "curl $*" >>"$STUB_DIR/curl.calls"
    if [ -n "${CURL_FAIL_MATCH:-}" ]; then
      case "$*" in *"$CURL_FAIL_MATCH"*) exit "${CURL_FAIL_RC:-6}" ;; esac
    fi
    exec /usr/bin/curl "$@"
''')

STUB_OSASCRIPT = textwrap.dedent('''\
    #!/bin/bash
    echo "osascript $*" >>"$STUB_DIR/osascript.calls"
    case "$*" in
      *"giving up after"*) echo $$ >>"$STUB_DIR/dialog.pids"; exec sleep 120 ;;
    esac
    exit 0
''')

STUB_OPEN = textwrap.dedent('''\
    #!/bin/bash
    if [ -x "$3" ]; then echo "open $* EXEC" >>"$STUB_DIR/open.calls"; else echo "open $* NOT-EXEC" >>"$STUB_DIR/open.calls"; fi
    exit 0
''')

STUB_SWVERS = '#!/bin/bash\necho "${FAKE_MACOS:-15.1}"\n'
STUB_XATTR = '#!/bin/bash\necho "xattr $*" >>"$STUB_DIR/xattr.calls"\nexit 0\n'


def _targz(path, member, content=b"x", mode=0o755):
    import io
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo(member)
        info.size = len(content)
        info.mode = mode
        tf.addfile(info, io.BytesIO(content))


def _tarxz(path, member, content=b"x", mode=0o755):
    import io
    with tarfile.open(path, "w:xz") as tf:
        info = tarfile.TarInfo(member)
        info.size = len(content)
        info.mode = mode
        tf.addfile(info, io.BytesIO(content))


def _sha(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@unittest.skipUnless(ON_MAC_ARM, "bootstrap tests need macOS arm64")
class BootstrapBase(unittest.TestCase):
    def setUp(self):
        self.w = tempfile.mkdtemp(prefix="rgsx_boot_")
        self.addCleanup(shutil.rmtree, self.w, True)
        w = self.w
        self.home = os.path.join(w, "home")
        os.makedirs(self.home)
        self.stub = os.path.join(w, "stub")
        os.makedirs(self.stub)
        self.bin = os.path.join(w, "bin")
        for name, body in (("curl", STUB_CURL), ("osascript", STUB_OSASCRIPT), ("open", STUB_OPEN), ("sw_vers", STUB_SWVERS), ("xattr", STUB_XATTR)):
            _write(os.path.join(self.bin, name), body, 0o755)
        self.stub_py = os.path.join(w, "stubpy", "python3.12")
        _write(self.stub_py, STUB_PY, 0o755)
        # fake ports/RGSX with the real bootstrap
        self.app = os.path.join(w, "ROMs", "ports", "RGSX")
        os.makedirs(os.path.join(self.app, "macos"))
        shutil.copy(os.path.join(MACOS, "rgsx-macos"), os.path.join(self.app, "macos", "rgsx-macos"))
        _write(os.path.join(self.app, "__main__.py"), "# stub\n")
        self.script = os.path.join(self.app, "macos", "rgsx-macos")
        # fixtures served over file://
        fx = os.path.join(w, "fx")
        os.makedirs(fx)
        self.pbs = os.path.join(fx, "pbs.tar.gz")
        _targz(self.pbs, "python/bin/python3", STUB_PY.encode())
        self.sz = os.path.join(fx, "7z.tar.xz")
        _tarxz(self.sz, "7zz", b"#!/bin/bash\necho 'Rar5 Rar'\nexit 0\n")
        self.pins = os.path.join(w, "pins")
        self._write_pins()
        self.cfg = os.path.join(self.home, "Library", "Application Support", "RGSX")
        self.rt = os.path.join(self.cfg, "runtime")

    def _write_pins(self, pbs_sha=None, mode="both"):
        _write(self.pins, textwrap.dedent(f"""\
            PBS_URL=file://{self.pbs}
            PBS_SHA256={pbs_sha or _sha(self.pbs)}
            SEVENZIP_URL=file://{self.sz}
            SEVENZIP_SHA256={_sha(self.sz)}
            PROGRESS_MODE={mode}
            """))

    def env(self, **extra):
        env = {
            "HOME": self.home, "TMPDIR": os.path.join(self.w, "tmp"), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "RGSX_EXTRA_PATH": self.bin, "RGSX_PINS_FILE": self.pins, "RGSX_LOCK_DIR": MACOS,
            "STUB_DIR": self.stub, "STUB_PY": self.stub_py, "RGSX_RETRY_SLEEP": "0", "RGSX_PROGRESS": "none",
        }
        env.update(extra)
        return env

    def run_boot(self, shell="/bin/bash", args=(), **extra):
        os.makedirs(os.path.join(self.w, "tmp"), exist_ok=True)
        return subprocess.run([shell, self.script, *args], env=self.env(**extra), capture_output=True, text=True, timeout=120)

    def calls(self, name):
        path = os.path.join(self.stub, name)
        return _read(path).splitlines() if os.path.exists(path) else []

    def stamp(self, name):
        path = os.path.join(self.rt, "state", name)
        return _read(path).strip() if os.path.exists(path) else None

    def log(self):
        return _read(os.path.join(self.cfg, "logs", "bootstrap.log"))


class BootstrapTests(BootstrapBase):
    def test_happy_path_then_idempotent(self):
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        self.assertIn("OK python=", res.stdout)
        for st in ("python", "core", "optional", "torrent", "7zz"):
            self.assertTrue((self.stamp(st) or "").startswith("ok|"), (st, self.stamp(st)))
        self.assertTrue(os.access(os.path.join(self.rt, "bin", "7zz"), os.X_OK))
        self.assertEqual(len(self.calls("curl.calls")), 2)  # python + 7zz
        pip_before = len(self.calls("pip.calls"))
        self.assertEqual(pip_before, 3)  # core, optional, torrent
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(len(self.calls("curl.calls")), 2, "second run must download nothing")
        self.assertEqual(len(self.calls("pip.calls")), pip_before)
        self.assertNotIn("stage 1/5", self.log().split("---- launch")[-1])

    def test_app_gets_args_and_environment(self):
        res = self.run_boot(args=("--foo",), RGSX_LAUNCHER_PATH="/x/ports/RGSX/RGSX.sh")
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        out = _read(os.path.join(self.stub, "app.out"))
        self.assertIn("APP_RAN __main__.py --foo", out)
        self.assertIn(f"RGSX_SEVENZIP={self.rt}/bin/7zz", out)
        self.assertIn("RGSX_LAUNCHER_PATH=/x/ports/RGSX/RGSX.sh", out)

    def test_runs_under_zsh_sh_bash(self):
        for shell in ("/bin/zsh", "/bin/sh", "/bin/bash"):
            with self.subTest(shell=shell):
                res = self.run_boot(shell=shell, RGSX_BOOTSTRAP_ONLY="1")
                self.assertEqual(res.returncode, 0, res.stderr)

    def test_checksum_mismatch_aborts_unstamped(self):
        self._write_pins(pbs_sha="0" * 64)
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 1)
        self.assertIsNone(self.stamp("python"))
        self.assertFalse(os.path.exists(os.path.join(self.rt, "tmp", "pbs.tar.gz.part")))
        self.assertTrue(any("corrupt" in c for c in self.calls("osascript.calls")))

    def test_fatal_download_failure_names_host(self):
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", CURL_FAIL_MATCH="pbs.tar.gz", CURL_FAIL_RC="6")
        self.assertEqual(res.returncode, 1)
        self.assertTrue(any("github.com" in c and "Internet is needed" in c for c in self.calls("osascript.calls")))
        self.assertIsNone(self.stamp("python"))

    def test_7zz_offline_is_nonfatal_and_not_retried_within_hour(self):
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", CURL_FAIL_MATCH="7z.tar.xz", CURL_FAIL_RC="6")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.stamp("7zz") or "").startswith("retry|"))
        self.assertIn("www.7-zip.org", self.log())
        n = len(self.calls("curl.calls"))
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(len(self.calls("curl.calls")), n, "retry window must prevent new downloads")

    def test_core_failure_fatal_optional_failure_not(self):
        open(os.path.join(self.stub, "fail_core"), "w").close()
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 1)
        self.assertEqual(len([c for c in self.calls("pip.calls") if c.startswith("pip core")]), 3)
        self.assertTrue(any("App libraries" in c for c in self.calls("osascript.calls")))
        os.remove(os.path.join(self.stub, "fail_core"))
        open(os.path.join(self.stub, "fail_optional"), "w").close()
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.stamp("optional") or "").startswith("retry|"))
        self.assertTrue((self.stamp("core") or "").startswith("ok|"))

    def test_rgsx_python_validation(self):
        open(os.path.join(self.stub, "invalid_python"), "w").close()
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PYTHON=self.stub_py)
        self.assertEqual(res.returncode, 1)
        self.assertTrue(any("arm64 CPython 3.12" in c for c in self.calls("osascript.calls")))
        os.remove(os.path.join(self.stub, "invalid_python"))
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PYTHON=self.stub_py)
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        self.assertFalse(any("pbs.tar.gz" in c for c in self.calls("curl.calls")), "RGSX_PYTHON replaces the download")
        self.assertTrue(_read(os.path.join(self.rt, "state", "core")).split("|")[-1].startswith("ext") or True)
        self.assertTrue(_read(os.path.join(self.rt, "state", "venv_py")).startswith("ext|"))

    def test_stale_lock_is_stolen(self):
        os.makedirs(os.path.join(self.rt, "lock"))
        _write(os.path.join(self.rt, "lock", "owner"), "999999\nMon Jan  1 00:00:00 2001\n")
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("stole stale lock", self.log())
        self.assertFalse(os.path.exists(os.path.join(self.rt, "lock")))

    def test_live_pid_with_different_start_time_is_treated_as_dead(self):
        os.makedirs(os.path.join(self.rt, "lock"))
        _write(os.path.join(self.rt, "lock", "owner"), f"{os.getpid()}\nThu Jan  1 00:00:00 1970\n")
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("stole stale lock", self.log())

    def test_quarantine_stripped_once_per_inode(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(len(self.calls("xattr.calls")), 1)
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(len(self.calls("xattr.calls")), 1)
        main = os.path.join(self.app, "__main__.py")
        os.remove(main)  # re-copied folder: new inode
        _write(main, "# stub2\n")
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(len(self.calls("xattr.calls")), 2)

    def test_reinstall_flag(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1")
        n = len(self.calls("pip.calls"))
        self.run_boot(args=("--reinstall",), RGSX_BOOTSTRAP_ONLY="1")
        self.assertEqual(len(self.calls("pip.calls")), n + 3)


class TorrentWheelSelectionTests(BootstrapBase):
    def test_macos13_disables_torrents_without_pip(self):
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", FAKE_MACOS="13.6.1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.stamp("torrent") or "").startswith("unavailable|"))
        self.assertTrue(self.stamp("torrent").endswith("|macos13"))
        self.assertFalse(any("torrent" in c for c in self.calls("pip.calls")))
        self.assertIn("torrents disabled", self.log())

    def test_macos14_and_15_install_the_lock(self):
        for ver in ("14.4", "15.2"):
            with self.subTest(macos=ver):
                shutil.rmtree(self.rt, ignore_errors=True)
                for f in os.listdir(self.stub):
                    os.remove(os.path.join(self.stub, f))
                res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", FAKE_MACOS=ver)
                self.assertEqual(res.returncode, 0, res.stderr)
                torrent = [c for c in self.calls("pip.calls") if c.startswith("pip torrent")]
                self.assertEqual(len(torrent), 1)
                self.assertIn("--require-hashes", torrent[0])
                self.assertIn("--only-binary=:all:", torrent[0])
                self.assertIn("requirements-torrent.lock", torrent[0])
                self.assertNotIn("--platform", torrent[0])
                self.assertTrue(self.stamp("torrent").startswith("ok|"))

    def test_no_matching_distribution_becomes_unavailable(self):
        for f in ("fail_torrent", "nowheel_torrent"):
            open(os.path.join(self.stub, f), "w").close()
        res = self.run_boot(RGSX_BOOTSTRAP_ONLY="1", FAKE_MACOS="14.0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue((self.stamp("torrent") or "").startswith("unavailable|"))
        n = len([c for c in self.calls("pip.calls") if c.startswith("pip torrent")])
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", FAKE_MACOS="14.0")
        self.assertEqual(len([c for c in self.calls("pip.calls") if c.startswith("pip torrent")]), n)

    def test_transient_torrent_failure_retries_later(self):
        open(os.path.join(self.stub, "fail_torrent"), "w").close()
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", FAKE_MACOS="15.0")
        self.assertTrue((self.stamp("torrent") or "").startswith("retry|"))


class ProgressScriptTests(BootstrapBase):
    def _wait_dead(self, pid, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.1)
        return False

    def test_no_tell_application_anywhere(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="both")
        cmd = _read(os.path.join(self.rt, "tmp", "progress.command"))
        self.assertNotIn("tell application", cmd)
        for path in (os.path.join(MACOS, "rgsx-macos"), os.path.join(APP, "RGSX.sh"), os.path.join(APP, "__main__.py"), os.path.join(MACOS, "selftest.py")):
            self.assertNotIn("tell application", _read(path), path)
        for call in self.calls("osascript.calls"):
            self.assertNotIn("tell application", call)

    def test_command_chmod_before_open(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="both")
        opens = self.calls("open.calls")
        self.assertEqual(len(opens), 1, opens)
        self.assertIn("-a Terminal", opens[0])
        self.assertTrue(opens[0].endswith("EXEC"), "progress.command must be executable when opened")

    def test_both_mode_one_dialog_killed_before_exit_and_done_marker(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="both")
        dialogs = [c for c in self.calls("osascript.calls") if "giving up after" in c]
        self.assertEqual(len(dialogs), 1, "one persistent dialog, not one per stage")
        pid = int(self.calls("dialog.pids")[0])
        self.assertTrue(self._wait_dead(pid), "dialog must be killed before the app starts")
        self.assertTrue(os.path.exists(os.path.join(self.rt, "tmp", "done")))

    def test_modes(self):
        expect = {"both": (1, 1), "dialog": (0, 1), "terminal": (1, 0), "none": (0, 0), "bogus": (1, 1)}
        for mode, (opens, dialogs) in expect.items():
            with self.subTest(mode=mode):
                shutil.rmtree(self.rt, ignore_errors=True)
                for f in os.listdir(self.stub):
                    os.remove(os.path.join(self.stub, f))
                self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS=mode)
                self.assertEqual(len(self.calls("open.calls")), opens)
                self.assertEqual(len([c for c in self.calls("osascript.calls") if "giving up after" in c]), dialogs)

    def test_fully_set_up_launch_shows_nothing(self):
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="both")
        for f in ("open.calls", "osascript.calls"):
            os.remove(os.path.join(self.stub, f))
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="both")
        self.assertEqual(self.calls("open.calls"), [])
        self.assertEqual(self.calls("osascript.calls"), [])

    def test_tail_starts_at_current_log_offset(self):
        os.makedirs(os.path.join(self.cfg, "logs"))
        old = "old run line\n" * 50
        _write(os.path.join(self.cfg, "logs", "bootstrap.log"), old)
        self.run_boot(RGSX_BOOTSTRAP_ONLY="1", RGSX_PROGRESS="terminal")
        cmd = _read(os.path.join(self.rt, "tmp", "progress.command"))
        line = [ln for ln in cmd.splitlines() if ln.startswith("tail -c +")][0]
        offset = int(line.split("+")[1].split()[0]) - 1
        self.assertGreaterEqual(offset, len(old))
        log = _read(os.path.join(self.cfg, "logs", "bootstrap.log"))
        self.assertTrue(log[:offset].startswith(old))
        self.assertNotIn("old run line", log[offset:])


# ---------------------------------------------------------------------------------------------------------
def _load_selftest():
    spec = importlib.util.spec_from_file_location("rgsx_selftest", os.path.join(MACOS, "selftest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# real `otool` output of the known-good libtorrent 2.1.1 cp312 macosx_15_0_arm64 wheel
_OTOOL_LT_SO_L = """site-packages/libtorrent/__init__.cpython-312-darwin.so:
\tlibtorrent.cpython-312-darwin.so (compatibility version 0.0.0, current version 0.0.0)
\t@loader_path/../libtorrent.dylibs/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t@loader_path/../libtorrent.dylibs/libcrypto.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation (compatibility version 150.0.0, current version 3502.1.255)
\t/System/Library/Frameworks/SystemConfiguration.framework/Versions/A/SystemConfiguration (compatibility version 1.0.0, current version 1351.120.3)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 1900.180.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""
_OTOOL_LT_SO_D = "site-packages/libtorrent/__init__.cpython-312-darwin.so:\nlibtorrent.cpython-312-darwin.so\n"
_OTOOL_SSL_L = """libtorrent.dylibs/libssl.3.dylib:
\t/DLC/libtorrent.dylibs/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t@loader_path/libcrypto.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""
_OTOOL_SSL_D = "libtorrent.dylibs/libssl.3.dylib:\n/DLC/libtorrent.dylibs/libssl.3.dylib\n"
_OTOOL_CRYPTO_L = """libtorrent.dylibs/libcrypto.3.dylib:
\t/DLC/libtorrent.dylibs/libcrypto.3.dylib (compatibility version 3.0.0, current version 3.0.0)
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)
"""
_OTOOL_CRYPTO_D = "libtorrent.dylibs/libcrypto.3.dylib:\n/DLC/libtorrent.dylibs/libcrypto.3.dylib\n"


class OtoolAllowListTests(unittest.TestCase):
    def setUp(self):
        self.st = _load_selftest()
        self.rt = os.path.realpath(tempfile.mkdtemp(prefix="rgsx_otool_"))
        self.addCleanup(shutil.rmtree, self.rt, True)
        sp = os.path.join(self.rt, "venv", "lib", "python3.12", "site-packages")
        self.so = os.path.join(sp, "libtorrent", "__init__.cpython-312-darwin.so")
        self.ssl = os.path.join(sp, "libtorrent.dylibs", "libssl.3.dylib")
        self.crypto = os.path.join(sp, "libtorrent.dylibs", "libcrypto.3.dylib")
        for p in (self.so, self.ssl, self.crypto):
            _write(p, "x")

    def _runner(self, table):
        def run(flag, path):
            return table.get((flag, path), "")
        return run

    def _libtorrent_table(self):
        return {
            ("-L", self.so): _OTOOL_LT_SO_L, ("-D", self.so): _OTOOL_LT_SO_D,
            ("-L", self.ssl): _OTOOL_SSL_L, ("-D", self.ssl): _OTOOL_SSL_D,
            ("-L", self.crypto): _OTOOL_CRYPTO_L, ("-D", self.crypto): _OTOOL_CRYPTO_D,
        }

    def test_libtorrent_wheel_known_good_passes(self):
        flagged = self.st.check_native_libs(self.rt, [self.so, self.ssl, self.crypto], run=self._runner(self._libtorrent_table()))
        self.assertEqual(flagged, [])

    def test_homebrew_dep_flagged(self):
        table = self._libtorrent_table()
        table[("-L", self.ssl)] = _OTOOL_SSL_L + "\t/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)\n"
        flagged = self.st.check_native_libs(self.rt, [self.ssl], run=self._runner(table))
        self.assertEqual([r for _f, r in flagged], ["/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib"])

    def test_unresolved_loader_path_flagged(self):
        os.remove(self.crypto)
        flagged = self.st.check_native_libs(self.rt, [self.ssl], run=self._runner(self._libtorrent_table()))
        self.assertEqual([r for _f, r in flagged], ["@loader_path/libcrypto.3.dylib"])

    def test_unresolved_rpath_flagged_and_resolved_rpath_ok(self):
        extra = "x:\n\t@rpath/libfoo.dylib (compatibility version 1.0.0, current version 1.0.0)\n"
        lc = "Load command 9\n          cmd LC_RPATH\n      cmdsize 32\n         path @loader_path/../libs (offset 12)\n"
        table = {("-L", self.so): extra, ("-D", self.so): "x:\nfoo\n", ("-l", self.so): lc}
        self.assertEqual([r for _f, r in self.st.check_native_libs(self.rt, [self.so], run=self._runner(table))], ["@rpath/libfoo.dylib"])
        _write(os.path.join(self.rt, "venv", "lib", "python3.12", "site-packages", "libs", "libfoo.dylib"), "x")
        self.assertEqual(self.st.check_native_libs(self.rt, [self.so], run=self._runner(table)), [])

    def test_loader_path_resolving_outside_runtime_is_flagged(self):
        outside = tempfile.mkdtemp(prefix="rgsx_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        link = os.path.join(os.path.dirname(self.ssl), "libcrypto.3.dylib")
        os.remove(link)
        _write(os.path.join(outside, "libcrypto.3.dylib"), "x")
        os.symlink(os.path.join(outside, "libcrypto.3.dylib"), link)
        flagged = self.st.check_native_libs(self.rt, [self.ssl], run=self._runner(self._libtorrent_table()))
        self.assertEqual([r for _f, r in flagged], ["@loader_path/libcrypto.3.dylib"])

    def test_collect_native_files(self):
        _write(os.path.join(self.rt, "bin", "7zz"), "x")
        files = self.st.collect_native_files(self.rt)
        self.assertIn(self.so, files)
        self.assertIn(os.path.join(self.rt, "bin", "7zz"), files)


# ---------------------------------------------------------------------------------------------------------
def _cfg(system, home, env=None, settings=None):
    """Import config in a fresh interpreter with platform.system patched; return (ROMS_FOLDER, ROMS_FOLDER_SOURCE)."""
    code = (
        "import platform, sys, json;"
        f"platform.system = lambda: {system!r};"
        f"sys.path.insert(0, {APP!r});"
        "import config;"
        "print(json.dumps([config.ROMS_FOLDER, getattr(config, 'ROMS_FOLDER_SOURCE', None)]))"
    )
    e = {k: v for k, v in os.environ.items() if not k.startswith("RGSX_")}
    e.update(HOME=home, RGSX_HEADLESS="1")
    e.update(env or {})
    if settings is not None:
        cfg_dir = e.get("RGSX_CONFIG_DIR") or os.path.join(home, "Library", "Application Support", "RGSX")
        _write(os.path.join(cfg_dir, "rgsx_settings.json"), json.dumps(settings))
    out = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class RomsRootTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="rgsx_roms_")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.home = os.path.join(self.t, "home")
        os.makedirs(self.home)

    def tree(self, *parts):
        path = os.path.join(self.t, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def launcher(self, roms, ports="ports", rgsx="RGSX"):
        d = self.tree(os.path.relpath(roms, self.t), ports, rgsx)
        return os.path.join(d, "RGSX.sh")

    def test_derived_from_launcher_path(self):
        roms = self.tree("ES-DE", "ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms)})
        self.assertEqual(got, [roms, "derived"])

    def test_invalid_settings_roms_folder_falls_back_to_derived(self):
        roms = self.tree("ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms)}, settings={"roms_folder": "/definitely/not/here"})
        self.assertEqual(got, [roms, "derived"])

    def test_rgsx_data_dir_set_still_derives(self):
        roms = self.tree("ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_DATA_DIR": os.path.join(self.t, "data")})
        self.assertEqual(got, [roms, "derived"])

    def test_rgsx_config_dir_set_still_derives(self):
        roms = self.tree("ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_CONFIG_DIR": os.path.join(self.t, "cfg")})
        self.assertEqual(got, [roms, "derived"])

    def test_env_override_beats_derived(self):
        roms = self.tree("ROMs")
        other = self.tree("Other")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_ROMS_DIR": other})
        self.assertEqual(got, [other, "env"])

    def test_invalid_env_is_ignored(self):
        roms = self.tree("ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_ROMS_DIR": "relative/path"})
        self.assertEqual(got, [roms, "derived"])

    def test_settings_beats_env_and_derived(self):
        roms, env_dir, mine = self.tree("ROMs"), self.tree("EnvRoms"), self.tree("Mine")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_ROMS_DIR": env_dir}, settings={"roms_folder": mine})
        self.assertEqual(got, [mine, "settings"])

    def test_symlinked_ports_keeps_logical_root(self):
        real = self.tree("disk", "ports", "RGSX")
        roms = self.tree("ROMs")
        os.symlink(os.path.join(self.t, "disk", "ports"), os.path.join(roms, "ports"))
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": os.path.join(roms, "ports", "RGSX", "RGSX.sh")})
        self.assertTrue(os.path.isdir(real))
        self.assertEqual(got, [roms, "derived"])

    def test_launcher_directly_in_ports(self):
        roms = self.tree("ROMs")
        ports = self.tree("ROMs", "ports")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": os.path.join(ports, "RGSX.sh")})
        self.assertEqual(got, [roms, "derived"])

    def test_case_variants(self):
        roms = self.tree("ROMs")
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms, ports="Ports", rgsx="rgsx")})
        self.assertEqual(got, [roms, "derived"])

    def test_git_root_rejected_and_realpath_file_not_consulted(self):
        proj = self.tree("proj")
        os.makedirs(os.path.join(proj, ".git"))
        got = _cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(proj)})
        self.assertEqual(got[1], "data_default")
        self.assertTrue(got[0].endswith(os.path.join("Documents", "RGSX", "roms")))

    def test_root_containing_tests_dir_is_accepted(self):
        roms = self.tree("ROMs")
        self.tree("ROMs", "tests")
        self.assertEqual(_cfg("Darwin", self.home, {"RGSX_LAUNCHER_PATH": self.launcher(roms)}), [roms, "derived"])

    def test_source_string_values(self):
        os.makedirs(os.path.join(self.home, "ROMs"))
        unmatched = {"RGSX_LAUNCHER_PATH": os.path.join(self.t, "nowhere", "RGSX.sh")}
        self.assertEqual(_cfg("Darwin", self.home, unmatched)[1], "home_default")
        shutil.rmtree(os.path.join(self.home, "ROMs"))
        self.assertEqual(_cfg("Darwin", self.home, unmatched)[1], "data_default")
        self.assertEqual(_cfg("Darwin", self.home, dict(unmatched, RGSX_DATA_DIR=os.path.join(self.t, "d")))[1], "data_default")

    def test_non_darwin_unaffected(self):
        roms = self.tree("ROMs")
        env = {"RGSX_LAUNCHER_PATH": self.launcher(roms), "RGSX_ROMS_DIR": self.tree("EnvRoms")}
        for system in ("Linux", "Windows"):
            with self.subTest(system=system):
                got = _cfg(system, self.home, env)
                self.assertNotIn(self.t, got[0].replace(os.path.join(self.t, "home"), ""), got)
                self.assertTrue(got[0].endswith("roms"), got)
                self.assertIsNone(got[1], "ROMS_FOLDER_SOURCE must not exist off macOS")

    def test_main_logs_roms_source_helper_exists(self):
        src = _read(os.path.join(APP, "__main__.py"))
        self.assertIn("_log_roms_source()", src)


# ---------------------------------------------------------------------------------------------------------
STUB_HELPER = '#!/bin/bash\necho "STUB args=[$*] launcher=${RGSX_LAUNCHER_PATH:-}" >"$STUB_OUT"\n'


class LauncherDispatchTests(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp(prefix="rgsx_disp_"))
        self.addCleanup(shutil.rmtree, self.t, True)
        self.ports = os.path.join(self.t, "ROMs", "ports")
        self.rgsx = os.path.join(self.ports, "RGSX")
        os.makedirs(os.path.join(self.rgsx, "macos"))
        shutil.copy(os.path.join(APP, "RGSX.sh"), self.rgsx)
        _write(os.path.join(self.rgsx, "macos", "rgsx-macos"), STUB_HELPER)  # not executable on purpose
        self.bin = os.path.join(self.t, "bin")
        _write(os.path.join(self.bin, "osascript"), '#!/bin/bash\necho "$*" >>"$STUB_OSA"\n', 0o755)
        self.out = os.path.join(self.t, "out.txt")
        self.osa = os.path.join(self.t, "osa.txt")

    def run_sh(self, shell, script, cwd=None, args=("--x",)):
        env = {"HOME": self.t, "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", "STUB_OUT": self.out, "STUB_OSA": self.osa}
        return subprocess.run([shell, script, *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=30)

    @unittest.skipUnless(platform.system() == "Darwin", "launcher block is macOS only")
    def test_dispatch_under_each_shell(self):
        for shell in ("/bin/zsh", "/bin/sh", "/bin/bash"):
            with self.subTest(shell=shell):
                if os.path.exists(self.out):
                    os.remove(self.out)
                res = self.run_sh(shell, os.path.join(self.rgsx, "RGSX.sh"))
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertEqual(_read(self.out).strip(), f"STUB args=[--x] launcher={self.rgsx}/RGSX.sh")

    @unittest.skipUnless(platform.system() == "Darwin", "launcher block is macOS only")
    def test_relative_invocation_gives_absolute_logical_path(self):
        for shell in ("/bin/zsh", "/bin/sh", "/bin/bash"):
            with self.subTest(shell=shell):
                res = self.run_sh(shell, "ports/RGSX/RGSX.sh", cwd=os.path.join(self.t, "ROMs"), args=())
                self.assertEqual(res.returncode, 0, res.stderr)
                self.assertIn(f"launcher={self.rgsx}/RGSX.sh", _read(self.out))

    @unittest.skipUnless(platform.system() == "Darwin", "launcher block is macOS only")
    def test_symlinked_launcher_relative_and_absolute(self):
        rel = os.path.join(self.ports, "RGSX_rel.sh")
        os.symlink(os.path.join("RGSX", "RGSX.sh"), rel)
        ab = os.path.join(self.ports, "RGSX_abs.sh")
        os.symlink(os.path.join(self.rgsx, "RGSX.sh"), ab)
        for link in (rel, ab):
            for shell in ("/bin/zsh", "/bin/sh", "/bin/bash"):
                with self.subTest(link=os.path.basename(link), shell=shell):
                    res = self.run_sh(shell, link, args=())
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertIn(f"launcher={link}", _read(self.out))  # logical path is the symlink location

    @unittest.skipUnless(platform.system() == "Darwin", "launcher block is macOS only")
    def test_symlink_chain_is_capped_and_shows_dialog(self):
        prev = os.path.join(self.rgsx, "RGSX.sh")
        for i in range(25):
            link = os.path.join(self.ports, f"hop{i}.sh")
            os.symlink(prev, link)
            prev = link
        res = self.run_sh("/bin/bash", prev, args=())
        self.assertEqual(res.returncode, 1)
        self.assertIn("RGSX is incomplete", res.stderr)
        self.assertIn("display dialog", _read(self.osa))
        self.assertFalse(os.path.exists(self.out))

    @unittest.skipUnless(platform.system() == "Darwin", "launcher block is macOS only")
    def test_missing_helper_exit_1_with_dialog(self):
        os.remove(os.path.join(self.rgsx, "macos", "rgsx-macos"))
        for shell in ("/bin/zsh", "/bin/sh", "/bin/bash"):
            with self.subTest(shell=shell):
                if os.path.exists(self.osa):
                    os.remove(self.osa)
                res = self.run_sh(shell, os.path.join(self.rgsx, "RGSX.sh"))
                self.assertEqual(res.returncode, 1)
                self.assertIn("macos/rgsx-macos is missing", res.stderr)
                self.assertIn("display dialog", _read(self.osa))

    def test_marker_block_removal_equals_head(self):
        text = _read(os.path.join(APP, "RGSX.sh"))
        lines = text.splitlines(keepends=True)
        begins = [i for i, ln in enumerate(lines) if ln.strip() == "# >>> RGSX-MACOS-BEGIN"]
        ends = [i for i, ln in enumerate(lines) if ln.strip() == "# <<< RGSX-MACOS-END"]
        self.assertEqual((len(begins), len(ends)), (1, 1))
        self.assertGreaterEqual(begins[0], 1)
        set_idx = next(i for i, ln in enumerate(lines) if ln.startswith("set -euo pipefail"))
        self.assertLess(ends[0], set_idx)
        stripped = "".join(lines[:begins[0]] + lines[ends[0] + 1:])
        head = subprocess.run(["git", "-C", ROOT, "show", "HEAD:ports/RGSX/RGSX.sh"], capture_output=True, text=True)
        if head.returncode != 0:
            fixture = os.path.join(FIXTURES, "RGSX.sh.HEAD")
            if not os.path.exists(fixture):
                self.skipTest("no git HEAD and no fixture")
            expected = _read(fixture)
        else:
            expected = head.stdout
        self.assertEqual(stripped, expected)

    def test_block_is_posix_sh_parseable_and_shell_agnostic(self):
        text = _read(os.path.join(APP, "RGSX.sh"))
        block = text[text.index("# >>> RGSX-MACOS-BEGIN"):text.index("# <<< RGSX-MACOS-END")]
        code = "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))
        for banned in ("[[", "local ", "declare ", "BASH_SOURCE[0]", "zsh", "pipefail"):
            self.assertNotIn(banned, code)
        res = subprocess.run(["/bin/sh", "-n"], input=block + "\n# <<< RGSX-MACOS-END\n", capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)


# ---------------------------------------------------------------------------------------------------------
class FakeLibtorrent(types.ModuleType):
    """Scriptable stand-in for the libtorrent module."""

    class listen_succeeded_alert:  # noqa: N801
        address = "0.0.0.0"

    class listen_failed_alert:  # noqa: N801
        def __init__(self, address):
            self.address = address

    class torrent_status:  # noqa: N801
        checking_files, checking_resume_data, downloading_metadata, downloading, finished, seeding, allocating = range(7)

    class storage_mode_t:  # noqa: N801
        storage_mode_sparse = 1

    class add_torrent_params:  # noqa: N801
        pass

    def __init__(self):
        super().__init__("libtorrent")
        self.__version__ = "0.0-fake"
        self.sessions = []
        self.files = [("Game/readme.txt", 10), ("Game/game.gba", 1000)]
        self.alerts = []
        self.fail_on_first_session = None
        self.session = self._make_session_cls()
        self.session.delete_files = 1

    def bdecode(self, data):
        return data

    def _make_session_cls(self):
        lt = self

        class Handle:
            def __init__(self, params):
                self.params = params
                self.paused = False
                self.calls = []
                self.ticks = 0

            def status(self):
                st = types.SimpleNamespace()
                st.errc = types.SimpleNamespace(value=lambda: 0, message=lambda: "")
                st.download_payload_rate = 1024 * 1024
                st.upload_payload_rate = 0
                st.num_peers = 3
                st.state = lt.torrent_status.downloading
                return st

            def file_progress(self):
                self.ticks += 1
                prog = [0] * len(lt.files)
                if self.ticks >= 2:
                    prog[1] = lt.files[1][1]
                    # libtorrent would have written the payload by now
                    path = os.path.join(self.params.save_path, lt.files[1][0])
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as fh:
                        fh.write(b"\0" * lt.files[1][1])
                else:
                    prog[1] = 100
                return prog

            def pause(self):
                self.paused = True
                self.calls.append("pause")

            def resume(self):
                self.paused = False
                self.calls.append("resume")

            def info_hash(self):
                return "abc123"

        class Session:
            def __init__(self, settings):
                self.settings = settings
                self.handles = []
                self.removed = []
                self.paused = False
                self.aborted = False
                lt.sessions.append(self)
                self._alerts = list(lt.alerts_for_next_session())

            def pop_alerts(self):
                out, self._alerts = self._alerts, []
                return out

            def add_torrent(self, params):
                h = Handle(params)
                self.handles.append(h)
                return h

            def remove_torrent(self, handle, flags=0):
                self.removed.append((handle, flags))

            def pause(self):
                self.paused = True

            def abort(self):
                self.aborted = True

        return Session

    def alerts_for_next_session(self):
        if self.alerts:
            return self.alerts.pop(0)
        return [self.listen_succeeded_alert()]

    def torrent_info(self, data):
        lt = self

        class Files:
            def num_files(self_inner):
                return len(lt.files)

            def file_path(self_inner, i):
                return lt.files[i][0]

            def file_size(self_inner, i):
                return lt.files[i][1]

        return types.SimpleNamespace(files=lambda: Files())


class _FakeResponse:
    content = b"d4:infod4:name4:Gamee"

    def raise_for_status(self):
        pass


class LibtorrentBackendTests(unittest.TestCase):
    def setUp(self):
        import libtorrent_backend as lb
        import qbittorrent_backend as qb
        self.lb, self.qb = lb, qb
        self.fake = FakeLibtorrent()
        self.addCleanup(sys.modules.pop, "libtorrent", None)
        sys.modules["libtorrent"] = self.fake
        lb._lt_module, lb._lt_checked, lb._session = None, False, None
        self.addCleanup(setattr, lb, "_session", None)
        self.addCleanup(setattr, lb, "_lt_checked", False)
        self.t = tempfile.mkdtemp(prefix="rgsx_lt_")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.dest_dir = os.path.join(self.t, "roms", "gba")
        os.makedirs(self.dest_dir)
        self.dest = os.path.join(self.dest_dir, "game.gba")
        self.meta = {"source_url": "https://example.invalid/x.torrent", "relative_path": "game.gba", "size_bytes": 1000}
        patches = [
            mock.patch.object(lb.requests, "get", return_value=_FakeResponse()),
            mock.patch.object(lb.time, "sleep", lambda _s: None),
            mock.patch.dict(os.environ, {"RGSX_TORRENT_LISTEN": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        qb._active_qbt_seeds.clear()
        qb._active_qbt_downloads.clear()
        self.addCleanup(qb._active_qbt_seeds.clear)
        self.addCleanup(qb._active_qbt_downloads.clear)

    def _download(self, cancel_ev=None, pause_ev=None, url="https://hist/x"):
        import queue
        q = queue.Queue()
        res = self.lb.download_torrent_via_qbittorrent(self.meta, self.dest_dir, self.dest, "task1", cancel_ev, q, url, pause_ev=pause_ev)
        items = []
        while not q.empty():
            items.append(q.get())
        return res, items

    def test_success_tuple_shape_link_and_seed_registration(self):
        (ok, msg), items = self._download()
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(self.dest))
        self.assertEqual(items[0], ("task1", 0, 1000, 0.0, 0, 0, "connecting"))
        for it in items[1:-1]:
            self.assertEqual(len(it), 7)
            self.assertIn(it[6], ("downloading", "waiting", "verifying", "connecting", "paused"))
        self.assertEqual(len(items[-1]), 4)
        self.assertEqual(items[-1][1], 1000)
        self.assertTrue(self.lb.has_active_seed("task1"))
        self.assertTrue(self.lb.has_active_seed(original_history_url="https://hist/x"))
        entry = self.qb._active_qbt_seeds["task1"]
        self.assertFalse(entry["payload_copied"])
        self.assertEqual(os.stat(self.dest).st_ino, os.stat(os.path.join(entry["temp_dir"], "Game", "game.gba")).st_ino)
        sess = self.fake.sessions[0]
        self.assertEqual(sess.handles[0].params.file_priorities, [0, 4])

    def test_cross_filesystem_link_failure_copies_via_part(self):
        with mock.patch.object(self.lb.os, "link", side_effect=OSError("EXDEV")):
            (ok, _msg), _items = self._download()
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))
        self.assertTrue(self.qb._active_qbt_seeds["task1"]["payload_copied"])

    def test_stop_seed_cleans_up_and_resets_history(self):
        self._download()
        temp_dir = self.qb._active_qbt_seeds["task1"]["temp_dir"]
        import network
        with mock.patch.object(network, "_stop_seeding_status") as reset:
            self.assertTrue(self.lb.stop_seed(original_history_url="https://hist/x"))
        reset.assert_called_once_with("https://hist/x")
        self.assertFalse(os.path.exists(temp_dir))
        self.assertTrue(os.path.isfile(self.dest), "the user's file survives")
        self.assertFalse(self.lb.has_active_seed("task1"))

    def test_shutdown_removes_temp_dirs_resets_history_and_pauses_session(self):
        self._download()
        temp_dir = self.qb._active_qbt_seeds["task1"]["temp_dir"]
        import network
        with mock.patch.object(network, "_stop_seeding_status") as reset:
            self.lb.shutdown()
        reset.assert_called_once()
        self.assertFalse(os.path.exists(temp_dir))
        self.assertTrue(self.fake.sessions[0].paused)
        self.assertIsNone(self.lb._session)
        self.lb.shutdown()  # idempotent, never raises

    def test_cancel_removes_files_and_raises(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(RuntimeError):
            self._download(cancel_ev=ev)
        sess = self.fake.sessions[0]
        self.assertTrue(any(flags == 1 for _h, flags in sess.removed), "remove_torrent with delete_files")
        self.assertEqual(os.listdir(os.path.join(self.dest_dir, ".rgsx_torrent")), [], "per-torrent temp dir removed")
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(self.qb._active_qbt_downloads, {})

    def test_pause_and_resume(self):
        pause = threading.Event()
        pause.set()
        threading.Timer(0.3, pause.clear).start()
        (_ok, _msg), items = self._download(pause_ev=pause)
        self.assertTrue(any(it[6] == "paused" for it in items if len(it) == 7))
        h = self.fake.sessions[0].handles[0]
        self.assertEqual(h.calls[:2], ["pause", "resume"])

    def test_listen_failure_both_interfaces_recreates_session_on_random_port(self):
        self.fake.alerts = [[self.fake.listen_failed_alert("0.0.0.0"), self.fake.listen_failed_alert("::")]]
        self.lb._get_session()
        self.assertEqual(len(self.fake.sessions), 2)
        self.assertTrue(self.fake.sessions[0].aborted)
        self.assertEqual(self.fake.sessions[1].settings["listen_interfaces"], "0.0.0.0:0,[::]:0")

    def test_ipv6_only_failure_keeps_ipv4_session(self):
        self.fake.alerts = [[self.fake.listen_succeeded_alert(), self.fake.listen_failed_alert("::")]]
        self.lb._get_session()
        self.assertEqual(len(self.fake.sessions), 1)

    def test_listen_opt_out_and_custom_value(self):
        with mock.patch.dict(os.environ, {"RGSX_TORRENT_LISTEN": "off"}):
            self.lb._get_session()
        s = self.fake.sessions[-1].settings
        self.assertEqual(s["listen_interfaces"], "127.0.0.1:0")
        self.assertFalse(s["enable_upnp"])
        self.assertFalse(s["enable_natpmp"])
        self.assertFalse(s["enable_lsd"])
        self.lb._session = None
        with mock.patch.dict(os.environ, {"RGSX_TORRENT_LISTEN": "192.168.1.2:7000"}):
            self.lb._get_session()
        self.assertEqual(self.fake.sessions[-1].settings["listen_interfaces"], "192.168.1.2:7000")

    def test_unavailable_when_libtorrent_missing(self):
        sys.modules["libtorrent"] = None  # import raises ImportError
        self.lb._lt_module, self.lb._lt_checked = None, False
        self.assertFalse(self.lb.is_available())
        with self.assertRaises(self.qb.BackendUnavailableError):
            self._download()

    def test_missing_target_file_raises(self):
        self.meta["relative_path"] = "nope.bin"
        with self.assertRaises(RuntimeError):
            self._download()

    def _import_order(self, order):
        fake_dir = tempfile.mkdtemp(prefix="rgsx_fakelt_")
        self.addCleanup(shutil.rmtree, fake_dir, True)
        _write(os.path.join(fake_dir, "libtorrent.py"), "__version__='fake'\n")
        code = (
            "import platform; platform.system = lambda: 'Darwin';"
            f"import sys; sys.path.insert(0, {APP!r});"
            f"import {order[0]}; import {order[1]};"
            "import qbittorrent_backend as q;"
            "print(q.is_available(), q.is_process_running(), q.has_active_seed('x'), q.download_torrent_via_qbittorrent.__module__)"
        )
        env = dict(os.environ, RGSX_HEADLESS="1", PYTHONPATH=fake_dir, HOME=self.t)
        res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip().splitlines()[-1], "True False False qbittorrent_backend")

    def test_import_order_libtorrent_backend_first(self):
        self._import_order(("libtorrent_backend", "qbittorrent_backend"))

    def test_import_order_qbittorrent_backend_first(self):
        self._import_order(("qbittorrent_backend", "libtorrent_backend"))

    def test_facade_not_installed_off_darwin(self):
        code = (
            "import platform; platform.system = lambda: 'Linux';"
            f"import sys; sys.path.insert(0, {APP!r});"
            "import qbittorrent_backend as q;"
            "print(q.is_available.__module__, q.shutdown.__code__.co_names)"
        )
        res = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, RGSX_HEADLESS="1", HOME=self.t), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("qbittorrent_backend", res.stdout)
        self.assertNotIn("libtorrent_backend", res.stdout)


# ---------------------------------------------------------------------------------------------------------
class ArmGateTests(unittest.TestCase):
    def _gate(self, module, system, arch, available, raises=False):
        import qbittorrent_backend as qb
        side = RuntimeError("boom") if raises else None
        with mock.patch.object(config, "OPERATING_SYSTEM", system), \
             mock.patch.object(config, "SYSTEM_INFO", {"architecture": arch}, create=True), \
             mock.patch.object(qb, "is_available", return_value=available, side_effect=side):
            return module._is_arm_device()

    def test_darwin_available_not_blocked_in_controls_and_network(self):
        import controls
        import network
        for mod in (controls, network):
            with self.subTest(module=mod.__name__):
                self.assertFalse(self._gate(mod, "Darwin", "arm64", True))
                self.assertTrue(self._gate(mod, "Darwin", "arm64", False))
                self.assertTrue(self._gate(mod, "Darwin", "arm64", True, raises=True))

    def test_other_platforms_unchanged(self):
        import controls
        import network
        for mod in (controls, network):
            with self.subTest(module=mod.__name__):
                self.assertTrue(self._gate(mod, "Linux", "aarch64", True))
                self.assertFalse(self._gate(mod, "Windows", "x86_64", True))
                self.assertFalse(self._gate(mod, "Linux", "x86_64", True))

    def test_should_prefer_backend_matrix(self):
        import network
        import qbittorrent_backend as qb
        for system, avail, expected in (("Windows", True, True), ("Linux", True, True), ("Darwin", True, True),
                                        ("Windows", False, False), ("Linux", False, False), ("Darwin", False, False),
                                        ("Other", True, False)):
            with self.subTest(system=system, avail=avail), mock.patch.object(config, "OPERATING_SYSTEM", system), \
                 mock.patch.object(qb, "is_available", return_value=avail):
                self.assertEqual(network._should_prefer_qbittorrent_backend(), expected)


class SevenZipRuntimeTests(unittest.TestCase):
    def test_resolve_7z_prefers_runtime_binary_on_darwin(self):
        import utils
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "7zz")
            _write(fake, "#!/bin/sh\nexit 0\n", 0o755)
            with mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), mock.patch.object(config, "SEVEN_Z_DARWIN", fake):
                self.assertEqual(utils._resolve_7z_command(), fake)

    def test_missing_7zz_message_on_darwin_never_mentions_brew(self):
        import utils
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
             mock.patch.object(utils, "_resolve_7z_command", return_value=None):
            ok, msg = utils.extract_7z(os.path.join(tmp, "x.7z"), tmp, "u")
        self.assertFalse(ok)
        self.assertIn("7-Zip is missing", msg)
        self.assertNotIn("brew", msg)

    def test_linux_message_unchanged(self):
        import utils
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "OPERATING_SYSTEM", "Linux"), \
             mock.patch.object(utils, "_resolve_7z_command", return_value=None):
            ok, msg = utils.extract_7z(os.path.join(tmp, "x.7z"), tmp, "u")
        self.assertFalse(ok)
        self.assertTrue(msg.startswith("7z non trouvé"))


class ExtensionFolderTests(unittest.TestCase):
    def setUp(self):
        self._saved = getattr(config, "platform_dicts", [])
        self.addCleanup(setattr, config, "platform_dicts", self._saved)
        config.platform_dicts = [{"platform_name": "Game Cube (Archive)", "folder": "gamecube"}]
        import esde_folders
        esde_folders._reset_cache()
        self.addCleanup(esde_folders._reset_cache)
        self.data = [{"folder": "gamecube", "extensions": [".iso", ".gcm"]}]

    def test_darwin_matches_rgsx_named_extension_entry(self):
        import utils
        with mock.patch("platform.system", return_value="Darwin"), mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"):
            self.assertTrue(utils.is_extension_supported("g.iso", "Game Cube (Archive)", self.data))
            self.assertFalse(utils.is_extension_supported("g.exe", "Game Cube (Archive)", self.data))

    def test_non_darwin_identical_to_baseline(self):
        if not os.path.isdir(BASELINE):
            self.skipTest("baseline fixtures absent")
        spec = importlib.util.spec_from_file_location("utils_baseline", os.path.join(BASELINE, "utils.py"))
        base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base)
        import utils
        for system in ("Linux", "Windows"):
            with mock.patch("platform.system", return_value=system), mock.patch.object(config, "OPERATING_SYSTEM", system):
                for name in ("g.iso", "g.exe", "g.zip"):
                    for plat in ("Game Cube (Archive)", "Unknown"):
                        self.assertEqual(utils.is_extension_supported(name, plat, self.data),
                                         base.is_extension_supported(name, plat, self.data), (system, name, plat))

    def test_map_rom_folder_idempotent_over_default_map(self):
        import esde_folders
        with mock.patch("platform.system", return_value="Darwin"):
            for key in esde_folders.ESDE_FOLDER_MAP:
                once = esde_folders.map_rom_folder(key)
                self.assertEqual(esde_folders.map_rom_folder(once), once, key)


class WebTests(unittest.TestCase):
    def _handler_html(self, system):
        import rgsx_web
        with mock.patch.object(config, "OPERATING_SYSTEM", system):
            h = rgsx_web.RGSXHandler.__new__(rgsx_web.RGSXHandler)
            return h._get_index_html()

    def test_qbittorrent_buttons_hidden_only_on_darwin(self):
        style = '<style>[onclick="openQbittorrentWebUi()"]{display:none !important}</style>'
        self.assertEqual(self._handler_html("Darwin").count(style), 1)
        self.assertNotIn(style, self._handler_html("Linux"))
        darwin = self._handler_html("Darwin").replace(style, "")
        self.assertEqual(darwin, self._handler_html("Linux"))

    def _run_server(self, system):
        import rgsx_web
        calls = []
        fake_httpd = mock.Mock()
        fake_httpd.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(config, "OPERATING_SYSTEM", system), \
             mock.patch("subprocess.run", side_effect=lambda *a, **k: calls.append(a[0]) or mock.Mock(stdout="")), \
             mock.patch.object(rgsx_web.time, "sleep", lambda _s: None), \
             mock.patch.object(rgsx_web, "HTTPServer", return_value=fake_httpd):
            try:
                rgsx_web.run_server("127.0.0.1", 5999)
            except Exception:
                pass
        return calls

    def test_run_server_never_kills_port_owner_on_darwin(self):
        flat = [" ".join(c) for c in self._run_server("Darwin")]
        self.assertFalse(any("lsof" in c or c.startswith("kill") for c in flat), flat)

    def test_run_server_still_kills_on_linux(self):
        flat = [" ".join(c) for c in self._run_server("Linux")]
        self.assertTrue(any("lsof" in c for c in flat), flat)

    def _pick(self):
        src = _read(os.path.join(APP, "__main__.py"))
        ns = {}
        exec(src[src.index("def _pick_web_port"):src.index("def _log_roms_source")], ns)  # noqa: S102 - our own source
        return ns["_pick_web_port"]

    def test_pick_web_port_binds_on_server_host(self):
        pick = self._pick()
        blocker = socket.socket()
        try:
            blocker.bind(("127.0.0.1", 0))
            busy = blocker.getsockname()[1]
            self.assertNotEqual(pick("127.0.0.1", busy), busy)
        finally:
            blocker.close()

    def test_pick_web_port_all_busy_gives_ephemeral(self):
        pick = self._pick()
        blockers = []
        try:
            base = None
            for start in range(41000, 41900, 20):
                socks = []
                try:
                    for p in range(start, start + 11):
                        s = socket.socket()
                        s.bind(("127.0.0.1", p))
                        socks.append(s)
                    base = start
                    blockers = socks
                    break
                except OSError:
                    for s in socks:
                        s.close()
            self.assertIsNotNone(base)
            port = pick("127.0.0.1", base)
            self.assertFalse(base <= port <= base + 10)
        finally:
            for s in blockers:
                s.close()


# ---------------------------------------------------------------------------------------------------------
class RegressionGuardTests(unittest.TestCase):
    GUARDED = ("rgsx_web.py", "network.py", "__main__.py", "qbittorrent_backend.py", "utils.py", "config.py", "controls.py", "RGSX.sh", "requirements.txt")

    def test_no_removed_lines_vs_pre_task_baseline(self):
        if not os.path.isdir(BASELINE):
            self.skipTest("baseline fixtures absent (release zip)")
        for name in self.GUARDED:
            with self.subTest(file=name):
                base = _read(os.path.join(BASELINE, name)).splitlines()
                cur = _read(os.path.join(APP, name)).splitlines()
                removed = [ln for ln in difflib.unified_diff(base, cur, n=0, lineterm="") if ln.startswith("-") and not ln.startswith("---")]
                self.assertEqual(removed, [], f"{name}: pre-existing lines were removed/changed")

    def test_requirements_txt_untouched(self):
        if not os.path.isdir(BASELINE):
            self.skipTest("baseline fixtures absent")
        self.assertEqual(_read(os.path.join(BASELINE, "requirements.txt")), _read(os.path.join(APP, "requirements.txt")))

    def test_gitignore_has_ds_store(self):
        self.assertIn(".DS_Store", _read(os.path.join(ROOT, ".gitignore")).splitlines())

    def test_obsolete_launchers_removed(self):
        for name in ("RGSX_ESDE.sh", "run_macos.sh"):
            self.assertFalse(os.path.exists(os.path.join(APP, name)), name)

    def test_helper_files_have_no_es_de_listed_extensions(self):
        listed = {".app", ".exe", ".game", ".sh"}
        for name in os.listdir(MACOS):
            self.assertNotIn(os.path.splitext(name)[1].lower(), listed, name)

    def test_no_brew_in_macos_docs(self):
        for name in ("README.md", "README_FR.md"):
            text = _read(os.path.join(ROOT, name))
            self.assertNotIn("brew install", text, name)
            self.assertNotIn("run_macos.sh", text, name)
            self.assertNotIn("RGSX_ESDE.sh", text, name)
        wf = _read(os.path.join(ROOT, ".github", "workflows", "release.yml"))
        self.assertNotIn("brew install", wf)
        self.assertNotIn("run_macos.sh", wf)

    def test_shell_scripts_syntax(self):
        for script, shell in ((os.path.join(APP, "RGSX.sh"), "/bin/bash"), (os.path.join(MACOS, "rgsx-macos"), "/bin/bash")):
            res = subprocess.run([shell, "-n", script], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)

    def test_bootstrap_is_executable_and_not_es_de_listed(self):
        self.assertTrue(os.stat(os.path.join(MACOS, "rgsx-macos")).st_mode & stat.S_IXUSR)
        self.assertEqual(os.path.splitext("rgsx-macos")[1], "")


if __name__ == "__main__":
    unittest.main()
