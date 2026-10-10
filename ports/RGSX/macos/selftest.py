"""RGSX macOS runtime self-test. Run: RGSX_SELFTEST=1 <ports>/RGSX/RGSX.sh (uses the runtime venv python).

check_native_libs() is a pure function (otool runner injectable) so it is unit-testable with canned output.
"""
import functools
import http.server
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import zipfile

_SYSTEM_PREFIXES = ("/usr/lib/", "/System/")
_REL_PREFIXES = ("@loader_path/", "@executable_path/", "@rpath/")


def run_otool(flag, path):
    out = subprocess.run(["otool", flag, path], capture_output=True, text=True)
    return out.stdout


def _refs(otool_l_output):
    """Dependencies from `otool -L`: drop the header line; keep the path before ' (compatibility'."""
    refs = []
    for line in otool_l_output.splitlines()[1:]:
        line = line.strip()
        if line:
            refs.append(line.split(" (compatibility", 1)[0].strip())
    return refs


def _own_ids(otool_d_output):
    """The library's own install-name id(s) from `otool -D` (first line is the file header)."""
    return {line.strip() for line in otool_d_output.splitlines()[1:] if line.strip()}


def _rpaths(otool_lc_output):
    paths = []
    lines = otool_lc_output.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "cmd LC_RPATH":
            for follow in lines[i + 1:i + 4]:
                m = re.match(r"\s*path (.+?) \(offset \d+\)", follow)
                if m:
                    paths.append(m.group(1))
                    break
    return paths


def _inside(path, runtime_real):
    real = os.path.realpath(path)
    return real == runtime_real or real.startswith(runtime_real + os.sep)


def _expand(prefix_path, file_dir, exec_dirs):
    """Expand @loader_path/@executable_path in an rpath entry; return candidate directories."""
    if prefix_path.startswith("@loader_path"):
        return [prefix_path.replace("@loader_path", file_dir, 1)]
    if prefix_path.startswith("@executable_path"):
        return [prefix_path.replace("@executable_path", d, 1) for d in exec_dirs]
    return [prefix_path]


def check_native_libs(runtime_dir, files, run=run_otool, main_binary=None):
    """Return [(file, reference)] for dependencies that are neither system libraries nor bundled in the runtime."""
    runtime_real = os.path.realpath(runtime_dir)
    flagged = []
    for f in files:
        file_dir = os.path.dirname(os.path.abspath(f))
        exec_dirs = [file_dir] + ([os.path.dirname(main_binary)] if main_binary else [])
        refs = _refs(run("-L", f))
        own = _own_ids(run("-D", f))
        own_base = {os.path.basename(i) for i in own}
        rpaths = None
        for ref in refs:
            if ref in own or ("/" not in ref and (ref in own_base or ref == os.path.basename(f))):
                continue  # the library's own install-name id (e.g. /DLC/..., or a bare name) / self-reference
            if ref.startswith(_SYSTEM_PREFIXES):
                continue
            ok = False
            if ref.startswith("@loader_path/"):
                cands = [ref.replace("@loader_path", file_dir, 1)]
            elif ref.startswith("@executable_path/"):
                cands = [ref.replace("@executable_path", d, 1) for d in exec_dirs]
            elif ref.startswith("@rpath/"):
                if rpaths is None:
                    rpaths = _rpaths(run("-l", f))
                cands = []
                for rp in rpaths:
                    for base in _expand(rp, file_dir, exec_dirs):
                        cands.append(os.path.join(base, ref[len("@rpath/"):]))
            else:
                cands = []  # absolute non-system path (Homebrew, /usr/local, ...) or an unexpected bare name
            for cand in cands:
                if os.path.exists(cand) and _inside(cand, runtime_real):
                    ok = True
                    break
            if not ok:
                flagged.append((f, ref))
    return flagged


def collect_native_files(runtime_dir):
    files = []
    for sub in ("venv", "python"):
        for root, _dirs, names in os.walk(os.path.join(runtime_dir, sub)):
            for n in names:
                p = os.path.join(root, n)
                if os.path.islink(p):
                    continue
                if n.endswith((".so", ".dylib")):
                    files.append(p)
    pyexe = os.path.join(runtime_dir, "python", "bin")
    if os.path.isdir(pyexe):
        for n in os.listdir(pyexe):
            p = os.path.join(pyexe, n)
            if re.fullmatch(r"python3\.\d+", n) and os.path.isfile(p) and not os.path.islink(p):
                files.append(p)
    seven = os.path.join(runtime_dir, "bin", "7zz")
    if os.path.isfile(seven):
        files.append(seven)
    return files


def main():
    os.environ.setdefault("RGSX_HEADLESS", "1")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, app)
    runtime = os.environ.get("RGSX_RUNTIME_DIR", "") or os.path.join(os.path.expanduser("~"), "Library", "Application Support", "RGSX", "runtime")
    res = []

    def check(name, fn):
        try:
            detail = fn()
            res.append((name, True, detail or ""))
        except Exception as exc:  # noqa: BLE001
            res.append((name, False, f"{type(exc).__name__}: {exc}"))

    def imports():
        import pygame, requests, PIL, watchdog  # noqa: F401,E401
        return f"pygame {pygame.version.ver}, requests {requests.__version__}, Pillow {PIL.__version__}"

    macos_major = int((platform.mac_ver()[0] or "0").split(".")[0] or 0)

    def torrent():
        if macos_major < 14:
            return f"skipped (macOS {macos_major} < 14: torrents disabled by design)"
        import libtorrent as lt
        lt.session({"listen_interfaces": "127.0.0.1:0"})
        return f"libtorrent {lt.__version__} session ok"

    def roms():
        import config
        src = getattr(config, "ROMS_FOLDER_SOURCE", "n/a")
        if os.environ.get("RGSX_LAUNCHER_PATH") and src not in ("derived", "env", "settings"):
            raise AssertionError(f"ROMS_FOLDER not derived from launcher (source={src}): {config.ROMS_FOLDER}")
        return f"ROMS_FOLDER={config.ROMS_FOLDER} source={src}"

    def sevenzip():
        import utils
        cmd = utils._resolve_7z_command()
        expected = os.path.join(runtime, "bin", "7zz")
        if os.path.realpath(str(cmd)) != os.path.realpath(expected):
            raise AssertionError(f"7z resolves to {cmd}, expected {expected}")
        out = subprocess.run([cmd, "i"], capture_output=True, text=True).stdout
        if "Rar5" not in out:
            raise AssertionError("7zz does not list Rar5")
        return f"{cmd} supports Rar5"

    def web_port_check():
        # Importing __main__.py would start the app; extract the function source instead
        src = open(os.path.join(app, "__main__.py"), encoding="utf-8").read()
        start = src.index("def _pick_web_port")
        end = src.index("def _maybe_show_roms_warning")
        ns = {}
        exec(src[start:end], ns)  # noqa: S102 - our own source file
        port = ns["_pick_web_port"]()
        return f"web port {port}"

    def mapping():
        from esde_folders import map_rom_folder
        assert map_rom_folder("gamecube") == "gc", map_rom_folder("gamecube")
        return "gamecube -> gc"

    def extraction():
        import config
        import utils
        with tempfile.TemporaryDirectory() as srv_dir:
            zpath = os.path.join(srv_dir, "t.zip")
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("rgsx_selftest.gb", b"\x00" * 16)
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=srv_dir)
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            import requests
            dest_dir = os.path.join(config.ROMS_FOLDER, "gb")
            made = not os.path.isdir(dest_dir)
            os.makedirs(dest_dir, exist_ok=True)
            local = os.path.join(srv_dir, "dl.zip")
            try:
                with open(local, "wb") as fh:
                    fh.write(requests.get(f"http://127.0.0.1:{httpd.server_address[1]}/t.zip", timeout=10).content)
                ok, msg = utils.extract_zip(local, dest_dir, "selftest")
                target = os.path.join(dest_dir, "rgsx_selftest.gb")
                if not ok or not os.path.isfile(target):
                    raise AssertionError(f"extract_zip failed: {ok} {msg}")
                return f"extracted into {dest_dir}"
            finally:
                httpd.shutdown()
                try:
                    os.remove(os.path.join(dest_dir, "rgsx_selftest.gb"))
                    if made:
                        os.rmdir(dest_dir)
                except OSError:
                    pass

    def native():
        files = collect_native_files(runtime)
        main_bin = os.path.join(runtime, "python", "bin", "python3")
        flagged = check_native_libs(runtime, files, main_binary=main_bin)
        if flagged:
            raise AssertionError("; ".join(f"{os.path.relpath(f, runtime)} -> {r}" for f, r in flagged[:10]))
        return f"{len(files)} native files, none reference non-system, non-bundled libraries"

    check("imports", imports)
    check("libtorrent", torrent)
    check("roms folder", roms)
    check("7zz", sevenzip)
    check("web port", web_port_check)
    check("rom folder mapping", mapping)
    check("zip extraction", extraction)
    check("native libs allow-list", native)
    failed = 0
    for name, ok, detail in res:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        failed += 0 if ok else 1
    print("SELFTEST " + ("OK" if not failed else f"FAILED ({failed})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
