"""Headless driver for tests/e2e_web_orphans.sh: runs ports/RGSX/__main__.py unchanged and exposes the Settings /
quit code paths through trigger files, because ES-DE-style launches have no external control channel.

Env: E2E_APP (RGSX app folder), E2E_TRIGGERS (directory polled for trigger files).
  restart_port  -> contents = new port: rgsx_settings.set_web_port + config.web_restart_callback() (what the Settings rows run)
  race          -> same restart in a thread and, 0.3 s later, the normal quit path (quit during restart)
  execl         -> Quit menu > Restart RGSX (restart_application: os.execl keeps the pid)
  quit          -> Quit menu > Quit RGSX (confirm_exit + confirm key)
Results go to <trigger>.done.
"""
import faulthandler
import json
import os
import runpy
import signal
import sys
import threading
import time

APP = os.environ["E2E_APP"]
TRIG = os.environ["E2E_TRIGGERS"]
sys.path.insert(0, APP)
os.chdir(APP)
faulthandler.register(signal.SIGUSR2, all_threads=True)  # debugging aid: kill -USR2 <pid> dumps all stacks


def _quit_menu(selection):
    import config
    import pygame
    deadline = time.time() + 150
    while config.menu_state in ("loading", "restart_popup") and time.time() < deadline:
        time.sleep(0.2)  # the startup loading screen would overwrite menu_state
    config.menu_state = "confirm_exit"
    config.confirm_selection = selection
    config.needs_redraw = True
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode="\r", scancode=40))


def _handle(name, arg):
    import config
    if name == "restart_port":
        from rgsx_settings import set_web_port
        set_web_port(int(arg))
        ok = config.web_restart_callback()
        return {"ok": ok, "runtime": getattr(config, "web_runtime", None)}
    if name == "race":
        from rgsx_settings import set_web_port
        set_web_port(int(arg))
        t = threading.Thread(target=config.web_restart_callback, daemon=True)
        t.start()
        time.sleep(0.3)
        _quit_menu(0)
        return {"started": True}
    if name == "execl":
        _quit_menu(1)
        return {"started": True}
    if name == "quit":
        _quit_menu(0)
        return {"started": True}
    return {"error": "unknown trigger"}


def _control():
    done = set()
    while True:
        time.sleep(0.2)
        try:
            names = os.listdir(TRIG)
        except OSError:
            continue
        for name in names:
            path = os.path.join(TRIG, name)
            if name.endswith(".done") or name in done or os.path.exists(path + ".done"):
                continue
            done.add(name)
            try:
                with open(path, encoding="utf-8") as fh:
                    arg = fh.read().strip()
                res = _handle(name, arg)
            except Exception as exc:  # report, never crash the app
                res = {"error": repr(exc)}
            with open(path + ".done", "w", encoding="utf-8") as fh:
                json.dump(res, fh)


DRIVER = os.path.abspath(sys.argv[0])


def _keep_driver_argv():
    """runpy.run_path rewrites sys.argv[0] to __main__.py; restore it so restart_application's os.execl re-runs this driver."""
    for _ in range(100):
        if sys.argv[0] != DRIVER:
            sys.argv[0] = DRIVER
            return
        time.sleep(0.1)


threading.Thread(target=_keep_driver_argv, daemon=True).start()
threading.Thread(target=_control, daemon=True).start()
runpy.run_path(os.path.join(APP, "__main__.py"), run_name="__main__")
