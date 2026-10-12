"""Tests for the macOS web-server lifecycle: pid file, stale-server matching/cleanup, restart handle, watchdog.
Run: python -m unittest discover -s tests -p 'test_macos_webproc.py'
"""
import ast
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

_TMP_HOME = tempfile.mkdtemp(prefix="rgsx_test_home_")
os.environ["HOME"] = _TMP_HOME
os.environ.pop("RGSX_CONFIG_DIR", None)
os.environ.pop("RGSX_DATA_DIR", None)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("RGSX_HEADLESS", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "ports", "RGSX")
sys.path.insert(0, APP)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from macos import webproc  # noqa: E402
import _proc  # noqa: E402

DARWIN = platform.system() == "Darwin"
SCRIPT = "/x/ports/RGSX/rgsx_web.py"
VENV_PY = "/Users/u/Library/Application Support/RGSX/runtime/venv/bin/python"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class PidfileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rgsx_pid_")

    def test_round_trip_and_atomic_replace(self):
        path = webproc.write_pidfile(1234, 5001, "0.0.0.0", SCRIPT, config_dir=self.dir)
        self.assertEqual(os.path.basename(path), "web_server.pid")
        data = webproc.read_pidfile(self.dir)
        self.assertEqual((data["pid"], data["port"], data["host"], data["script"]), (1234, 5001, "0.0.0.0", SCRIPT))
        self.assertIn("started", data)
        webproc.write_pidfile(4321, 5002, "127.0.0.1", SCRIPT, config_dir=self.dir)
        self.assertEqual(webproc.read_pidfile(self.dir)["pid"], 4321)
        self.assertEqual(os.listdir(self.dir), ["web_server.pid"])  # no tmp file left behind

    def test_corrupt_or_missing_is_none(self):
        self.assertIsNone(webproc.read_pidfile(self.dir))
        for bad in ("{not json", "[]", json.dumps({"pid": "12"}), json.dumps({"pid": 1})):
            with open(os.path.join(self.dir, "web_server.pid"), "w") as fh:
                fh.write(bad)
            self.assertIsNone(webproc.read_pidfile(self.dir), bad)

    def test_remove_is_idempotent(self):
        webproc.write_pidfile(5, 1, "h", SCRIPT, config_dir=self.dir)
        webproc.remove_pidfile(self.dir)
        webproc.remove_pidfile(self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "web_server.pid")))


class MatchingTests(unittest.TestCase):
    def test_matches_exact_script(self):
        for cmd in (f"/usr/bin/python3 {SCRIPT} --host 0.0.0.0 --port 5002",
                    f"{VENV_PY} {SCRIPT} --host 127.0.0.1 --port 5001 --parent-pid 99",
                    f"/Library/Frameworks/Python.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python {SCRIPT}",
                    f"python3.11 {SCRIPT}",
                    f"/usr/bin/python3 -u {SCRIPT} --port 5000"):
            self.assertTrue(webproc.is_rgsx_web_cmd(cmd, SCRIPT), cmd)

    def test_does_not_match_lookalikes(self):
        for cmd in (f"vim {SCRIPT}",
                    "tail -f /x/ports/RGSX/logs/rgsx_web.log",
                    "grep rgsx_web.py",
                    f"grep {SCRIPT} /etc/hosts",
                    "/usr/bin/python3 /other/ports/RGSX/rgsx_web.py --port 5000",
                    f"/usr/bin/python3 {SCRIPT}.bak",
                    f"/usr/bin/python3 {SCRIPT}x",
                    f"/usr/bin/python3 prefix{SCRIPT}",
                    f"python -c import time; time.sleep(60) rgsx_web.py {SCRIPT}",
                    f"python3 -m http.server {SCRIPT}",
                    f"/usr/bin/env FOO=1 {SCRIPT}",
                    "sleep 100",
                    "",
                    None):
            self.assertFalse(webproc.is_rgsx_web_cmd(cmd, SCRIPT), cmd)

    def test_script_must_be_rgsx_web(self):
        self.assertFalse(webproc.is_rgsx_web_cmd("python /x/other.py", "/x/other.py"))

    def test_path_with_spaces(self):
        script = "/Users/u/My Games/ports/RGSX/rgsx_web.py"
        self.assertTrue(webproc.is_rgsx_web_cmd(f"{VENV_PY} {script} --port 5000", script))
        self.assertFalse(webproc.is_rgsx_web_cmd(f"{VENV_PY} /Users/u/My Games2/ports/RGSX/rgsx_web.py", script))

    def test_parse_parent_pid(self):
        self.assertEqual(webproc.parse_parent_pid(f"py {SCRIPT} --port 1 --parent-pid 77"), 77)
        self.assertEqual(webproc.parse_parent_pid(f"py {SCRIPT}"), 0)


class FindStaleTests(unittest.TestCase):
    def test_only_stale_servers_of_this_install_for_this_user(self):
        me, uid = 500, 501
        table = [
            (600, 1, uid, f"{VENV_PY} {SCRIPT} --port 5001"),                  # orphan -> stale
            (601, 700, uid, f"{VENV_PY} {SCRIPT} --port 5002"),                # parent dead -> stale
            (602, me, uid, f"{VENV_PY} {SCRIPT} --port 5003"),                 # child of this pid (post-execl) -> stale
            (603, 800, uid, f"{VENV_PY} {SCRIPT} --port 5004"),                # parent alive: another RGSX -> keep
            (604, 1, uid, f"{VENV_PY} {SCRIPT} --port 5005"),                  # excluded pid
            (605, 1, uid + 1, f"{VENV_PY} {SCRIPT} --port 5006"),              # other user
            (606, 1, uid, "/usr/bin/python3 /other/ports/RGSX/rgsx_web.py"),   # other install
            (607, 1, uid, f"vim {SCRIPT}"),                                    # editor
            (608, 1, uid, "sleep 100"),
            (500, 1, uid, f"{VENV_PY} {SCRIPT}"),                              # ourselves
            (1, 0, uid, f"{VENV_PY} {SCRIPT}"),
        ]
        alive = lambda p: p in (800, me)  # noqa: E731
        found = webproc.find_stale_servers(SCRIPT, exclude_pids={604}, table=table, uid=uid, own_pid=me, alive=alive)
        self.assertEqual(sorted(p for p, _ in found), [600, 601, 602])


@unittest.skipUnless(DARWIN, "uses macOS ps/lsof")
class RealProcessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rgsx_proc_")
        self.script = os.path.join(self.dir, "rgsx_web.py")
        with open(self.script, "w") as fh:
            fh.write("import signal, sys, time\n"
                     "if 'ignore-term' in sys.argv: signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     "time.sleep(120)\n")
        self.addCleanup(_proc.kill_all)

    def _orphan(self, *extra):
        """Start the stand-in detached from us (parent = init), return its pid."""
        cmd = " ".join([f"'{sys.executable}'", f"'{self.script}'"] + list(extra))
        out = subprocess.run(["/bin/sh", "-c", f"{cmd} >/dev/null 2>&1 & echo $!"], capture_output=True, text=True)
        pid = int(out.stdout.strip())
        self.addCleanup(lambda: os.kill(pid, signal.SIGKILL) if webproc.pid_alive(pid) else None)
        for _ in range(50):
            if webproc.proc_command(pid):
                break
            time.sleep(0.1)
        return pid

    def test_unrelated_process_is_never_terminated(self):
        sleeper = _proc.spawn_tracked([sys.executable, "-c", "import time; time.sleep(60)"])
        self.assertFalse(webproc.terminate_pid(sleeper.pid, self.script, grace=0.3))
        time.sleep(0.2)
        self.assertIsNone(sleeper.poll())  # still alive: command line did not match

    def test_term_ignoring_server_is_killed(self):
        pid = self._orphan("ignore-term")
        started = time.time()
        self.assertTrue(webproc.terminate_pid(pid, self.script, grace=0.8))
        self.assertLess(time.time() - started, 6)
        self.assertFalse(webproc.pid_alive(pid))

    def test_cleanup_stale_kills_orphan_but_not_lookalikes(self):
        orphan = self._orphan()
        other_dir = tempfile.mkdtemp(prefix="rgsx_other_")
        lookalike = _proc.spawn_tracked([sys.executable, "-c", "import time; time.sleep(60)", "rgsx_web.py", self.script])
        sleeper = _proc.spawn_tracked(["/bin/sleep", "60"])
        webproc.write_pidfile(orphan, 1, "h", self.script, config_dir=other_dir)
        stopped = webproc.cleanup_stale(self.script, config_dir=other_dir)
        self.assertEqual(stopped, [orphan])
        self.assertFalse(webproc.pid_alive(orphan))
        self.assertIsNone(lookalike.poll())
        self.assertIsNone(sleeper.poll())
        self.assertIsNone(webproc.read_pidfile(other_dir))

    def test_pidfile_with_reused_pid_is_forgotten_not_killed(self):
        sleeper = _proc.spawn_tracked(["/bin/sleep", "60"])
        d = tempfile.mkdtemp(prefix="rgsx_reuse_")
        webproc.write_pidfile(sleeper.pid, 1, "h", self.script, config_dir=d)
        self.assertEqual(webproc.cleanup_stale(self.script, config_dir=d), [])
        self.assertIsNone(sleeper.poll())
        self.assertIsNone(webproc.read_pidfile(d))

    def test_port_released(self):
        port = _free_port()
        self.assertTrue(webproc.port_released("127.0.0.1", port, timeout=0.2))
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        self.addCleanup(srv.close)
        self.assertFalse(webproc.port_released("127.0.0.1", port, timeout=0.3))
        self.assertTrue(webproc.port_released("127.0.0.1", port, timeout=0.3, pid=os.getpid() + 1))
        srv.close()
        self.assertTrue(webproc.port_released("127.0.0.1", port, timeout=1.0))

    def test_web_server_watchdog_exits_when_parent_is_gone(self):
        dead = subprocess.Popen(["/usr/bin/true"])
        dead.wait()
        port = _free_port()
        env = dict(os.environ, HOME=tempfile.mkdtemp(prefix="rgsx_wd_"), RGSX_HEADLESS="1")
        proc = _proc.spawn_tracked([sys.executable, os.path.join(APP, "rgsx_web.py"), "--host", "127.0.0.1",
                                    "--port", str(port), "--parent-pid", str(dead.pid)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("web server did not exit after its parent disappeared")


class _FakeProc:
    _next = 9000

    def __init__(self, *a, **kw):
        _FakeProc._next += 1
        self.pid = _FakeProc._next
        self.args = a[0] if a else kw.get("args")
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.wait_calls = []
        self.stubborn = False  # ignores terminate()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


def _load_main_namespace():
    """Exec the web-server section of __main__.py (importing it would start pygame) into a namespace."""
    with open(os.path.join(APP, "__main__.py"), encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    wanted_funcs = {"_web_script_path", "_stop_web_server_darwin", "_mark_web_shutting_down", "_shutdown_web_server_atexit",
                    "_install_web_cleanup_hooks", "_force_exit", "_on_terminate_signal", "start_web_server", "stop_web_server", "restart_web_server", "_pick_web_port"}
    wanted_assign = {"web_server_process", "_web_proc_lock", "_web_shutting_down", "_web_hooks_installed", "_web_restart_lock", "_web_signal_timer"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            body.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted_assign for t in node.targets):
            body.append(node)
    ns = {"os": os, "sys": sys, "subprocess": subprocess, "threading": threading, "config": config,
          "logger": mock.MagicMock(), "__name__": "main_under_test"}
    exec(compile(ast.Module(body=body, type_ignores=[]), "__main__.py", "exec"), ns)
    return ns


class HandleTests(unittest.TestCase):
    """start/stop/restart on a fake Popen: the tracked handle must always point at the single live server."""

    def setUp(self):
        self.ns = _load_main_namespace()
        self.cfgdir = tempfile.mkdtemp(prefix="rgsx_cfg_")
        patches = [
            mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"),
            mock.patch.object(config, "CONFIG_FOLDER", self.cfgdir),
            mock.patch.object(config, "log_dir", self.cfgdir),
            mock.patch.object(config, "APP_FOLDER", APP),
            mock.patch.object(config, "web_runtime", None, create=True),
            mock.patch("time.sleep"),
            mock.patch.object(webproc, "cleanup_stale", return_value=[]),
            mock.patch.object(webproc, "pid_alive", side_effect=lambda pid: self._alive.get(pid, False)),
            mock.patch.object(webproc, "port_released", return_value=True),
            mock.patch.object(webproc, "terminate_pid", return_value=True),
        ]
        self._alive = {}
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        orig_popen = subprocess.Popen

        def tracking_popen(*a, **kw):
            proc = _FakeProc(*a, **kw)
            self._alive[proc.pid] = True
            self.procs.append(proc)
            return proc
        self.procs = []
        subprocess.Popen = tracking_popen
        self.addCleanup(setattr, subprocess, "Popen", orig_popen)

        # a terminated fake is gone
        orig_terminate = _FakeProc.terminate

        def terminate(proc):
            orig_terminate(proc)
            if proc.returncode is not None:
                self._alive[proc.pid] = False
        self._term = mock.patch.object(_FakeProc, "terminate", terminate)
        self._term.start()
        self.addCleanup(self._term.stop)
        self.env = mock.patch.dict(os.environ, {"RGSX_WEB_PORT": str(_free_port()), "RGSX_WEB_HOST": "127.0.0.1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_start_tracks_handle_pidfile_and_parent_pid(self):
        ns = self.ns
        self.assertTrue(ns["start_web_server"]())
        proc = ns["web_server_process"]
        self.assertIs(proc, self.procs[0])
        cmd = proc.args
        self.assertEqual(cmd[cmd.index("--parent-pid") + 1], str(os.getpid()))
        data = webproc.read_pidfile(self.cfgdir)
        self.assertEqual(data["pid"], proc.pid)
        self.assertEqual(data["port"], config.web_runtime["port"])
        webproc.cleanup_stale.assert_called_once()

    def test_restart_replaces_handle_and_stops_old_server_first(self):
        ns = self.ns
        self.assertTrue(ns["start_web_server"]())
        old = ns["web_server_process"]
        self.assertTrue(ns["restart_web_server"]())
        new = ns["web_server_process"]
        self.assertIsNot(new, old)
        self.assertTrue(old.terminated)
        self.assertEqual(len(self.procs), 2)
        self.assertEqual(webproc.read_pidfile(self.cfgdir)["pid"], new.pid)
        self.assertEqual(config.web_restart_status, "ok")
        self.assertEqual([p for p in self.procs if self._alive.get(p.pid)], [new])  # exactly one live server

    def test_stop_logs_clean_only_after_verified(self):
        ns = self.ns
        ns["start_web_server"]()
        proc = ns["web_server_process"]
        with mock.patch.object(webproc, "port_released", return_value=False):
            self.assertFalse(ns["stop_web_server"]())
        messages = [c.args[0] for c in ns["logger"].info.call_args_list]
        self.assertNotIn("Serveur web arrêté proprement", messages)
        self.assertIs(ns["web_server_process"], proc)  # handle kept so the next stop retries
        self.assertTrue(ns["stop_web_server"]())
        self.assertIn("Serveur web arrêté proprement", [c.args[0] for c in ns["logger"].info.call_args_list])
        self.assertIsNone(ns["web_server_process"])
        self.assertIsNone(webproc.read_pidfile(self.cfgdir))

    def test_stubborn_server_is_killed_and_failure_keeps_handle(self):
        ns = self.ns
        ns["start_web_server"]()
        proc = ns["web_server_process"]
        proc.stubborn = True
        with mock.patch.object(webproc, "terminate_pid", return_value=False):
            # kill() sets returncode, but the pid is still reported alive: not "stopped"
            self._alive[proc.pid] = True
            with mock.patch.object(webproc, "pid_alive", return_value=True):
                self.assertFalse(ns["stop_web_server"]())
        self.assertTrue(proc.terminated and proc.killed)
        self.assertIs(ns["web_server_process"], proc)
        self.assertNotIn("Serveur web arrêté proprement", [c.args[0] for c in ns["logger"].info.call_args_list])

    def test_restart_does_not_spawn_second_server_when_stop_fails(self):
        ns = self.ns
        ns["start_web_server"]()
        old = ns["web_server_process"]
        with mock.patch.dict(ns, {"_stop_web_server_darwin": lambda: False}):
            self.assertFalse(ns["restart_web_server"]())
        self.assertIs(ns["web_server_process"], old)
        self.assertEqual(len(self.procs), 1)
        self.assertEqual(config.web_restart_status, "failed")

    def test_no_start_after_shutdown_flag(self):
        ns = self.ns
        ns["_mark_web_shutting_down"]()
        self.assertFalse(ns["start_web_server"]())
        self.assertEqual(self.procs, [])

    def test_restart_racing_quit_leaves_no_server(self):
        """Quit during a restart: the quit waits for the restart, no new server is spawned, nothing stays alive."""
        ns = self.ns
        ns["start_web_server"]()
        started, proceed = threading.Event(), threading.Event()
        real_start = ns["start_web_server"]

        def slow_start():
            started.set()
            proceed.wait(5)
            return real_start()
        ns["start_web_server"] = slow_start
        t = threading.Thread(target=ns["restart_web_server"])
        t.start()
        self.assertTrue(started.wait(5))
        q = threading.Thread(target=ns["_shutdown_web_server_atexit"])
        q.start()
        threading.Event().wait(0.3)  # quit is now flagged and blocked on the lock held by the restart
        proceed.set()
        t.join(5)
        q.join(5)
        self.assertIsNone(ns["web_server_process"])
        self.assertEqual([p for p in self.procs if self._alive.get(p.pid)], [])
        self.assertEqual(len(self.procs), 1)  # the restart never spawned a replacement

    def test_atexit_hook_installed_once(self):
        ns = self.ns
        with mock.patch("atexit.register") as reg:
            ns["_install_web_cleanup_hooks"]()
            ns["_install_web_cleanup_hooks"]()
        self.assertEqual(reg.call_count, 1)

    def test_signal_requests_quit_and_second_signal_forces_exit(self):
        ns = self.ns
        ns["shutdown_downloads"] = mock.MagicMock()
        ns["start_web_server"]()
        proc = ns["web_server_process"]
        self.addCleanup(setattr, config, "quit_requested", False)
        config.quit_requested = False
        with mock.patch.object(threading, "Timer") as timer, mock.patch.object(os, "_exit") as exit_:
            ns["_on_terminate_signal"](signal.SIGTERM, None)
            self.assertTrue(config.quit_requested)
            timer.assert_called_once()
            self.assertEqual(timer.call_args.args[0], 10.0)
            exit_.assert_not_called()
            ns["_on_terminate_signal"](signal.SIGTERM, None)  # second signal: no more waiting
            exit_.assert_called_once_with(128 + signal.SIGTERM)
        self.assertTrue(proc.terminated)  # the force path stopped the web server first
        self.assertIsNone(ns["web_server_process"])
        ns["shutdown_downloads"].assert_called_once()

    def test_signal_handlers_registered_for_term_hup_int(self):
        ns = self.ns
        with mock.patch("atexit.register"), mock.patch("signal.signal") as sig:
            ns["_install_web_cleanup_hooks"]()
        self.assertEqual({c.args[0] for c in sig.call_args_list}, {signal.SIGTERM, signal.SIGHUP, signal.SIGINT})
        self.assertTrue(all(c.args[1] is ns["_on_terminate_signal"] for c in sig.call_args_list))

    def test_start_returns_true_without_second_spawn_when_already_running(self):
        ns = self.ns
        ns["start_web_server"]()
        self.assertTrue(ns["start_web_server"]())
        self.assertEqual(len(self.procs), 1)


class NonDarwinParityTests(unittest.TestCase):
    def setUp(self):
        self.ns = _load_main_namespace()
        p = mock.patch.object(config, "OPERATING_SYSTEM", "Linux")
        p.start()
        self.addCleanup(p.stop)

    def test_linux_stop_keeps_terminate_wait5_kill(self):
        proc = mock.MagicMock()
        proc.wait.side_effect = [subprocess.TimeoutExpired("x", 5), None]
        self.ns["web_server_process"] = proc
        self.ns["stop_web_server"]()
        proc.terminate.assert_called_once_with()
        self.assertEqual(proc.wait.call_args_list[0], mock.call(timeout=5))
        proc.kill.assert_called_once_with()
        self.assertIsNone(self.ns["web_server_process"])

    def test_linux_restart_is_noop(self):
        self.assertFalse(self.ns["restart_web_server"]())

    def test_linux_command_has_no_parent_pid(self):
        captured = []
        with mock.patch.object(subprocess, "Popen", side_effect=lambda cmd, **kw: captured.append(cmd) or _FakeProc(cmd)), \
                mock.patch("time.sleep"), mock.patch.object(config, "log_dir", tempfile.mkdtemp()), \
                mock.patch.object(config, "APP_FOLDER", APP):
            self.ns["start_web_server"]()
        self.assertTrue(captured)
        self.assertNotIn("--parent-pid", captured[0])


if __name__ == "__main__":
    unittest.main()
