"""macOS only: track, validate and stop the RGSX web server child process.

Pure helpers with no side effects on import. Nothing here ever signals a process unless its command line
proves it is `<python> <exact rgsx_web.py path of this install>` (so a reused pid or an unrelated process whose
arguments merely mention rgsx_web.py is never touched).
"""
import json
import logging
import os
import re
import signal
import socket
import subprocess
import time

logger = logging.getLogger(__name__)

PIDFILE_NAME = "web_server.pid"
_PYTHON_BASENAME = re.compile(r"^python[\d.]*$", re.IGNORECASE)


# ---- pid file -------------------------------------------------------------------------------------------------
def pidfile_path(config_dir=None):
    if config_dir is None:
        import config
        config_dir = config.CONFIG_FOLDER
    return os.path.join(config_dir, PIDFILE_NAME)


def write_pidfile(pid, port, host, script, config_dir=None, parent=None):
    """Atomically write {pid, port, host, script, parent, started} (tmp file + os.replace)."""
    path = pidfile_path(config_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"pid": int(pid), "port": port, "host": host, "script": script,
            "parent": os.getpid() if parent is None else parent, "started": time.time()}
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
    return path


def read_pidfile(config_dir=None):
    """Return the pid file dict, or None when missing/corrupt/invalid."""
    try:
        with open(pidfile_path(config_dir), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("pid"), int) and data["pid"] > 1:
            return data
    except (OSError, ValueError):
        pass
    return None


def remove_pidfile(config_dir=None):
    try:
        os.remove(pidfile_path(config_dir))
    except OSError:
        pass


# ---- process table --------------------------------------------------------------------------------------------
def _run_ps(args):
    try:
        res = subprocess.run(["/bin/ps"] + args, capture_output=True, text=True, timeout=5)
        return res.stdout if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def proc_command(pid):
    """Full command line of pid, or None when it does not exist."""
    out = _run_ps(["-ww", "-p", str(int(pid)), "-o", "command="]).strip()
    return out or None


def ps_table():
    """[(pid, ppid, uid, command)] for every process visible to this user."""
    rows = []
    for line in _run_ps(["-axww", "-o", "pid=,ppid=,uid=,command="]).splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
    return rows


def pid_alive(pid):
    """True while pid exists and is not a zombie child we can reap."""
    try:
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---- matching -------------------------------------------------------------------------------------------------
def is_rgsx_web_cmd(cmdline, script_path):
    """True only for `<python...> <script_path> [args]` where script_path is the exact rgsx_web.py of this install.

    `ps` prints argv joined by spaces without quoting (the venv path contains "Application Support"), so the
    script path is located as a whole argument instead of splitting the command line.
    """
    if not cmdline or not script_path or os.path.basename(script_path) != "rgsx_web.py":
        return False
    candidates = {script_path, os.path.realpath(script_path)}
    for script in candidates:
        start = 0
        while True:
            idx = cmdline.find(script, start)
            if idx < 0:
                break
            start = idx + 1
            end = idx + len(script)
            if idx == 0 or cmdline[idx - 1] != " " or (end != len(cmdline) and cmdline[end] != " "):
                continue
            # prefix = `<python>` optionally followed by interpreter flags; `-c`/`-m` code is never a server launch
            head, *flags = cmdline[:idx].strip().split(" -")
            if _PYTHON_BASENAME.match(os.path.basename(head)) and not any(f[:1] in ("c", "m") for f in flags):
                return True
    return False


def parse_parent_pid(cmdline):
    """Value of `--parent-pid N` in a command line, or 0."""
    parts = cmdline.split()
    for i, tok in enumerate(parts[:-1]):
        if tok == "--parent-pid" and parts[i + 1].isdigit():
            return int(parts[i + 1])
    return 0


def _is_orphaned(ppid, own_pid, alive=pid_alive):
    """A web server is stale when its parent is init, dead, or this very process (execl keeps our pid)."""
    return ppid <= 1 or ppid == own_pid or not alive(ppid)


def find_stale_servers(script_path, exclude_pids=(), table=None, uid=None, own_pid=None, alive=pid_alive):
    """[(pid, command)] of stale RGSX web servers of THIS install owned by the current user.

    A server still attached to another live process (e.g. a second running RGSX or a manual run from a shell)
    is not stale and is never returned.
    """
    uid = os.getuid() if uid is None else uid
    own_pid = os.getpid() if own_pid is None else own_pid
    exclude = set(exclude_pids) | {own_pid}
    found = []
    for pid, ppid, puid, cmd in (ps_table() if table is None else table):
        if pid in exclude or puid != uid or pid <= 1:
            continue
        if not is_rgsx_web_cmd(cmd, script_path):
            continue
        if _is_orphaned(ppid, own_pid, alive):
            found.append((pid, cmd))
    return found


# ---- stopping -------------------------------------------------------------------------------------------------
def _wait_gone(pid, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


def terminate_pid(pid, script_path, grace=3.0, kill_grace=2.0):
    """SIGTERM, wait up to grace, then SIGKILL. Returns True only when pid is gone.

    The command line is re-validated right before every signal, so a recycled pid is never signalled.
    """
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        return False
    try:
        if pid == os.getpgid(0):
            return False
    except OSError:
        pass
    if not pid_alive(pid):
        return True
    if not is_rgsx_web_cmd(proc_command(pid), script_path):
        # exited in between (gone) or never ours (not touched)
        return not pid_alive(pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    if _wait_gone(pid, grace):
        return True
    if not is_rgsx_web_cmd(proc_command(pid), script_path):
        return not pid_alive(pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return _wait_gone(pid, kill_grace)


def _listener_pids(port):
    try:
        res = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return {int(p) for p in res.stdout.split() if p.isdigit()}


def port_released(host, port, timeout=2.0, pid=None):
    """True when nothing (or, with pid, no longer that pid) listens on port. Polls up to timeout seconds."""
    deadline = time.time() + timeout
    while True:
        pids = _listener_pids(port)
        if pids is None:  # no lsof: fall back to a connect probe
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.3)
            try:
                released = probe.connect_ex(("127.0.0.1", int(port))) != 0
            finally:
                probe.close()
        else:
            released = not pids if pid is None else pid not in pids
        if released:
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.1)


def cleanup_stale(script_path, keep_pids=(), config_dir=None, **kw):
    """Stop stale RGSX web servers left by a previous session/crash. Returns the list of pids stopped.

    Sources: the pid file (validated against its recorded script path) and a scan of this user's processes for
    `<python> <this install's rgsx_web.py>`. Unrelated processes are never matched.
    """
    own = os.getpid()
    keep = set(keep_pids) | {own}
    victims = {}
    info = read_pidfile(config_dir)
    if info and info["pid"] not in keep:
        rec_script = info.get("script") or script_path
        cmd = proc_command(info["pid"])
        if cmd and is_rgsx_web_cmd(cmd, rec_script):
            if _is_orphaned(_ppid_of(info["pid"]), own):
                victims[info["pid"]] = (rec_script, info.get("port"))
        else:
            remove_pidfile(config_dir)  # dead, or pid reused by something else: forget it, never kill it
    for pid, cmd in find_stale_servers(script_path, exclude_pids=keep, **kw):
        victims.setdefault(pid, (script_path, None))
    stopped = []
    for pid, (script, port) in victims.items():
        if terminate_pid(pid, script):
            stopped.append(pid)
            logger.info("Stale RGSX web server pid=%s port=%s stopped", pid, port)
        else:
            logger.warning("Stale RGSX web server pid=%s could not be stopped", pid)
    if info and info["pid"] not in keep and not pid_alive(info["pid"]):
        remove_pidfile(config_dir)
    return stopped


def _ppid_of(pid):
    out = _run_ps(["-p", str(int(pid)), "-o", "ppid="]).strip()
    return int(out) if out.isdigit() else 0
