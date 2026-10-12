"""Process helpers for tests: every child lives in its own session and is killed (whole group) on cleanup/exit."""
import atexit
import os
import signal
import subprocess
import time

_SPAWNED = []


def _kill_group(pgid, grace=3.0):
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):
                return
            time.sleep(0.05)


def kill_all():
    while _SPAWNED:
        proc = _SPAWNED.pop()
        _kill_group(proc.pid)
        try:
            proc.wait(timeout=1)
        except Exception:
            pass


def spawn_tracked(cmd, **kw):
    """subprocess.Popen in a new session (so a whole process tree can be killed); killed at exit/cleanup."""
    kw.setdefault("start_new_session", True)
    proc = subprocess.Popen(cmd, **kw)
    _SPAWNED.append(proc)
    return proc


def kill_tracked(proc):
    """SIGTERM, wait, SIGKILL the process group of a spawn_tracked child."""
    _kill_group(proc.pid)
    try:
        proc.wait(timeout=1)
    except Exception:
        pass


atexit.register(kill_all)
