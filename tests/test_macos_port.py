"""Tests for the macOS port. Run: python -m unittest discover -s tests -v

Branch guards are exercised with a patched platform so Windows/Linux regressions fail loudly.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Keep config/log side effects out of the real home directory
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

import config  # noqa: E402
import utils  # noqa: E402


def _run_config(system, home, extra_env=None):
    """Import config in a fresh interpreter with platform.system patched; return (SAVE, DATA, ROMS, log_dir)."""
    code = (
        "import platform, sys, json;"
        f"platform.system = lambda: {system!r};"
        f"sys.path.insert(0, {APP!r});"
        "import config;"
        "print(json.dumps([config.SAVE_FOLDER, config.DATA_FOLDER, config.ROMS_FOLDER, config.log_dir]))"
    )
    env = dict(os.environ, HOME=home, RGSX_HEADLESS="1")
    for key in ("RGSX_CONFIG_DIR", "RGSX_DATA_DIR", "RGSX_APP_DIR", "RGSX_LAUNCHER_PATH", "RGSX_ROMS_DIR"):
        env.pop(key, None)
    env.update(extra_env or {})
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def _run_settings(system, home):
    code = (
        "import platform, sys, json;"
        f"platform.system = lambda: {system!r};"
        f"sys.path.insert(0, {APP!r});"
        "import rgsx_settings as s;"
        "d = s.load_rgsx_settings();"
        "print(json.dumps([d['display']['fullscreen'], d['show_unsupported_platforms'], d['allow_unknown_extensions']]))"
    )
    env = dict(os.environ, HOME=home, RGSX_HEADLESS="1", RGSX_CONFIG_DIR=os.path.join(home, "cfg"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class ConfigPaths(unittest.TestCase):
    def test_config_darwin_paths(self):
        with tempfile.TemporaryDirectory() as home:
            save, data, roms, log_dir = _run_config("Darwin", home)
            home = os.path.realpath(home) if not save.startswith(home) else home
            self.assertTrue(save.endswith(os.path.join("Library", "Application Support", "RGSX")))
            self.assertTrue(data.endswith(os.path.join("Documents", "RGSX")))
            self.assertEqual(roms, os.path.join(data, "roms"))
            self.assertEqual(log_dir, os.path.join(save, "logs"))

    def test_config_darwin_env_override(self):
        with tempfile.TemporaryDirectory() as home:
            save, data, _roms, _log = _run_config("Darwin", home, {"RGSX_CONFIG_DIR": "/tmp/rgsx_cfg", "RGSX_DATA_DIR": "/tmp/rgsx_data"})
            self.assertEqual((save, data), ("/tmp/rgsx_cfg", "/tmp/rgsx_data"))

    def test_config_linux_paths_unchanged(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as home:
                save, data, _roms, log_dir = _run_config(system, home)
                self.assertNotIn("Library", save)
                self.assertNotIn("Documents", data)
                self.assertTrue(save.endswith(os.path.join("saves", "ports", "rgsx")))
                self.assertTrue(log_dir.endswith(os.path.join("RGSX", "logs")))


class SettingsDefaults(unittest.TestCase):
    def test_settings_defaults_darwin(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(_run_settings("Darwin", home), [False, True, True])

    def test_settings_defaults_other_os_unchanged(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as home:
                self.assertEqual(_run_settings(system, home), [True, False, False])


class WebHost(unittest.TestCase):
    def setUp(self):
        import rgsx_settings
        self.s = rgsx_settings

    def test_precedence_darwin(self):
        r = self.s.resolve_web_host
        self.assertEqual(r("Darwin", "192.168.1.5", "0.0.0.0"), "192.168.1.5")
        self.assertEqual(r("Darwin", None, "0.0.0.0"), "0.0.0.0")
        self.assertEqual(r("Darwin", "", "10.0.0.2"), "10.0.0.2")
        self.assertEqual(r("Darwin", None, None), "127.0.0.1")

    def test_invalid_falls_back(self):
        r = self.s.resolve_web_host
        for bad in ("evil", "999.1.1.1", "::1", 5, "0.0.0.0/0", "1.2.3"):
            with self.subTest(bad=bad):
                self.assertEqual(r("Darwin", None, bad), "127.0.0.1")
        self.assertEqual(r("Darwin", "bogus", "0.0.0.0"), "0.0.0.0")

    def test_non_darwin_unchanged(self):
        for system in ("Linux", "Windows"):
            self.assertEqual(self.s.resolve_web_host(system, "127.0.0.1", "127.0.0.1"), "0.0.0.0")

    def test_default_setting_darwin_only(self):
        code = ("import platform, sys, json;platform.system = lambda: %r;sys.path.insert(0, %r);"
                "import rgsx_settings as s;print(json.dumps(s.load_rgsx_settings().get('web_host')))")
        for system, expected in (("Darwin", "127.0.0.1"), ("Linux", None), ("Windows", None)):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as home:
                env = dict(os.environ, HOME=home, RGSX_HEADLESS="1", RGSX_CONFIG_DIR=os.path.join(home, "cfg"))
                out = subprocess.run([sys.executable, "-c", code % (system, APP)], env=env,
                                     capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), expected)

    def test_log_lines_local_only(self):
        lines = self.s.web_access_log_lines("127.0.0.1", "192.168.1.83", 5001)
        text = " ".join(m for _l, m in lines)
        self.assertIn("local-only", text)
        self.assertIn("web_host", text)
        self.assertNotIn("192.168.1.83", text)
        self.assertNotIn("Accès réseau", text)

    def test_log_lines_lan(self):
        lines = self.s.web_access_log_lines("0.0.0.0", "192.168.1.83", 5001)
        self.assertIn(("info", "Accès réseau: http://192.168.1.83:5001"), lines)
        self.assertTrue(any(l == "warning" and "NO authentication" in m for l, m in lines))


def _fake_exe(directory, name):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class SevenZip(unittest.TestCase):
    def test_resolve_7z_darwin_uses_path_and_skips_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = _fake_exe(tmp, "7zz")
            bundled = _fake_exe(tmp, "bundled_7zz")
            with mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
                 mock.patch.object(config, "SEVEN_Z_LINUX", bundled, create=True), \
                 mock.patch.dict(os.environ, {"PATH": tmp}):
                self.assertEqual(utils._resolve_7z_command(), fake)

    def test_resolve_7z_linux_prefers_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fake_exe(tmp, "7zz")
            bundled = _fake_exe(tmp, "bundled_7zz")
            with mock.patch.object(config, "OPERATING_SYSTEM", "Linux"), \
                 mock.patch.object(config, "SEVEN_Z_LINUX", bundled, create=True), \
                 mock.patch.dict(os.environ, {"PATH": tmp}):
                self.assertEqual(utils._resolve_7z_command(), bundled)


class Rar(unittest.TestCase):
    def test_extract_rar_darwin_delegates_to_7z(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
             mock.patch.object(utils.shutil, "which", return_value=None), \
             mock.patch.object(utils, "extract_7z", return_value=(True, None)) as ext:
            self.assertEqual(utils.extract_rar("x.rar", tmp, "u"), (True, None))
            ext.assert_called_once()

    def test_extract_rar_linux_does_not_delegate(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "OPERATING_SYSTEM", "Linux"), \
             mock.patch.object(utils.shutil, "which", return_value=None), \
             mock.patch.object(utils.subprocess, "run", side_effect=FileNotFoundError), \
             mock.patch.object(utils, "extract_7z", return_value=(True, None)) as ext:
            utils.extract_rar("x.rar", tmp, "u")
            ext.assert_not_called()


class PlatformTools(unittest.TestCase):
    def test_handle_xbox_darwin_without_tool(self):
        with mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
             mock.patch.object(utils.time, "sleep"), \
             mock.patch.object(utils.shutil, "which", return_value=None):
            ok, msg = utils.handle_xbox("/tmp", [])
            self.assertFalse(ok)
            self.assertIn("extract-xiso", msg)

    def test_lolroms_command_darwin_uses_curl(self):
        import network
        with mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
             mock.patch.object(network.shutil, "which", side_effect=lambda n: "/usr/bin/curl" if n == "curl" else None):
            self.assertEqual(network._resolve_lolroms_external_command(), ("curl", "/usr/bin/curl"))

    def test_lolroms_command_linux_uses_wget(self):
        import network
        with mock.patch.object(config, "OPERATING_SYSTEM", "Linux"), \
             mock.patch.object(network.shutil, "which", side_effect=lambda n: "/usr/bin/wget" if n == "wget" else None):
            self.assertEqual(network._resolve_lolroms_external_command(), ("wget", "/usr/bin/wget"))

    def test_qbt_executable_none_on_darwin(self):
        import qbittorrent_backend as qb
        with mock.patch.object(config, "OPERATING_SYSTEM", "Darwin"), \
             mock.patch.object(qb.shutil, "which", return_value=None):
            self.assertIsNone(qb._find_qbittorrent_executable())


class KeyboardProfile(unittest.TestCase):
    def _load(self, system):
        import controls
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(config, "OPERATING_SYSTEM", system), \
             mock.patch.object(config, "joystick", False, create=True), \
             mock.patch.object(config, "keyboard", False, create=True):
            return controls.load_controls_config(os.path.join(tmp, "missing.json"))

    def test_keyboard_profile_selected_on_darwin(self):
        self.assertEqual(self._load("Darwin")["start"]["key"], 112)

    def test_keyboard_profile_other_os_unchanged(self):
        self.assertEqual(self._load("Linux")["start"]["key"], 1073742054)

    def test_profile_files_are_valid_json(self):
        for name in ("keyboard.json", "keyboard_macos.json"):
            with open(os.path.join(APP, "assets", "controls", name), encoding="utf-8") as f:
                self.assertIsInstance(json.load(f), dict)


import esde_folders  # noqa: E402
_ESDE_ROWS = {
    "3ds": "n3ds", "amiga500": "amiga", "amigacdtv": "cdtv", "c20": "vic20", "cplus4": "plus4",
    "cdi": "cdimono1", "gamecube": "gc", "jaguar": "atarijaguar", "lynx": "atarilynx",
    "MSX2+ (Archive)": "msx2", "o2em": "odyssey2", "sg1000": "sg-1000", "wswan": "wonderswan",
    "wswanc": "wonderswancolor",
}
_ESDE_UNCHANGED = ["bios", "fds", "snes", "psx", "windows", "ports", "dos", "xbox", "switch", "gba",
                   "advision", "atom", "chihiro", "lindbergh", "namco2x6", "pico", "teknoparrot"]
class EsdeFolderMapping(unittest.TestCase):
    def setUp(self):
        esde_folders._reset_cache()
        self.addCleanup(esde_folders._reset_cache)
        self._saved_dicts = getattr(config, "platform_dicts", [])
        self.addCleanup(setattr, config, "platform_dicts", self._saved_dicts)
        config.platform_dicts = [{"platform_name": "Game Cube (Archive)", "folder": "gamecube"},
                                 {"platform_name": "- BIOS by TMCTV -", "folder": "bios"}]
    def test_table_has_14_rows(self):
        self.assertEqual(esde_folders.ESDE_FOLDER_MAP, _ESDE_ROWS)
    def test_darwin_maps_all_rows(self):
        with mock.patch("platform.system", return_value="Darwin"):
            for src, dst in _ESDE_ROWS.items():
                self.assertEqual(esde_folders.map_rom_folder(src), dst, src)
            for name in _ESDE_UNCHANGED + ["", None, "unknownthing"]:
                self.assertEqual(esde_folders.map_rom_folder(name), name)
    def test_linux_windows_identity(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), mock.patch("platform.system", return_value=system):
                for name in list(_ESDE_ROWS) + _ESDE_UNCHANGED:
                    self.assertEqual(esde_folders.map_rom_folder(name), name)
    def test_dest_folder_name_and_resolve(self):
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(utils._get_dest_folder_name("Game Cube (Archive)"), "gc")
            self.assertEqual(utils.resolve_platform_folder("Game Cube (Archive)"), "gc")
            self.assertEqual(utils._get_dest_folder_name("- BIOS by TMCTV -"), "bios")
        with mock.patch("platform.system", return_value="Linux"):
            self.assertEqual(utils._get_dest_folder_name("Game Cube (Archive)"), "gamecube")
            self.assertEqual(utils.resolve_platform_folder("Game Cube (Archive)"), "gamecube")
    def _with_settings(self, content):
        save = tempfile.mkdtemp(prefix="rgsx_settings_")
        self.addCleanup(shutil.rmtree, save, True)
        with open(os.path.join(save, "rgsx_settings.json"), "w", encoding="utf-8") as f:
            f.write(content)
        patcher = mock.patch.object(config, "SAVE_FOLDER", save)
        patcher.start()
        self.addCleanup(patcher.stop)
        esde_folders._reset_cache()
    def test_settings_override(self):
        self._with_settings(json.dumps({"rom_folder_map": {"gamecube": "gamecube", "pico": "segapico", "x": "", "y": 3}}))
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(esde_folders.map_rom_folder("gamecube"), "gamecube")  # default disabled
            self.assertEqual(esde_folders.map_rom_folder("pico"), "segapico")
            self.assertEqual(esde_folders.map_rom_folder("x"), "x")
            self.assertEqual(esde_folders.map_rom_folder("3ds"), "n3ds")
        esde_folders._reset_cache()
        with mock.patch("platform.system", return_value="Linux"):
            self.assertEqual(esde_folders.map_rom_folder("pico"), "pico")
    def test_mapping_can_be_disabled(self):
        self._with_settings(json.dumps({"esde_folder_mapping": False}))
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(esde_folders.map_rom_folder("gamecube"), "gamecube")
    def test_bad_settings_fall_back(self):
        self._with_settings("{not json")
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(esde_folders.map_rom_folder("gamecube"), "gc")
    def test_targets_exist_in_installed_esde(self):
        xml = "/Applications/ES-DE.app/Contents/Resources/resources/systems/macos/es_systems.xml"
        if not os.path.isfile(xml):
            self.skipTest("ES-DE not installed")
        import xml.etree.ElementTree as ET
        names = {e.text for e in ET.parse(xml).getroot().iter("name")}
        for dst in _ESDE_ROWS.values():
            self.assertIn(dst, names)
class RomsFolderDefault(unittest.TestCase):
    def test_darwin_uses_home_roms_when_present(self):
        with tempfile.TemporaryDirectory() as home:
            os.mkdir(os.path.join(home, "ROMs"))
            roms = _run_config("Darwin", home)[2]
            self.assertEqual(os.path.basename(roms), "ROMs")
            self.assertTrue(os.path.realpath(roms).startswith(os.path.realpath(home)))
    def test_darwin_without_home_roms_keeps_documents_default(self):
        with tempfile.TemporaryDirectory() as home:
            roms = _run_config("Darwin", home)[2]
            self.assertTrue(roms.endswith(os.path.join("Documents", "RGSX", "roms")))
    def test_darwin_data_dir_env_beats_home_roms(self):
        with tempfile.TemporaryDirectory() as home:
            os.mkdir(os.path.join(home, "ROMs"))
            roms = _run_config("Darwin", home, {"RGSX_DATA_DIR": "/tmp/rgsx_data"})[2]
            self.assertEqual(roms, "/tmp/rgsx_data/roms")
    def test_darwin_settings_roms_folder_beats_home_roms(self):
        with tempfile.TemporaryDirectory() as home:
            os.mkdir(os.path.join(home, "ROMs"))
            custom = os.path.join(home, "Other")
            os.mkdir(custom)
            cfg = os.path.join(home, "Library", "Application Support", "RGSX")
            os.makedirs(cfg)
            with open(os.path.join(cfg, "rgsx_settings.json"), "w", encoding="utf-8") as f:
                json.dump({"roms_folder": custom}, f)
            self.assertEqual(_run_config("Darwin", home)[2], custom)
    def test_linux_windows_ignore_home_roms(self):
        for system in ("Linux", "Windows"):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as home:
                os.mkdir(os.path.join(home, "ROMs"))
                self.assertNotEqual(os.path.realpath(_run_config(system, home)[2]), os.path.realpath(os.path.join(home, "ROMs")))
class WebPort(unittest.TestCase):
    def setUp(self):
        import rgsx_settings
        self.s = rgsx_settings
    def test_normalize(self):
        n = self.s.normalize_web_port
        for ok, expected in ((1024, 1024), (65535, 65535), ("5001", 5001), (" 5002 ", 5002), (5000, 5000)):
            self.assertEqual(n(ok), expected)
        for bad in (80, 1023, 65536, "abc", "", "-5", "5000.5", "99999999", True, False, 5000.5, None, [5000]):
            with self.subTest(bad=bad):
                self.assertIsNone(n(bad))
    def test_precedence_darwin(self):
        r = self.s.resolve_web_port
        self.assertEqual(r("Darwin", "5100", 5200), 5100)
        self.assertEqual(r("Darwin", None, 5200), 5200)
        self.assertEqual(r("Darwin", "", 5200), 5200)
        self.assertEqual(r("Darwin", "abc", 5200), 5200)
        self.assertEqual(r("Darwin", "80", 70000), 5000)
        self.assertEqual(r("Darwin", None, None), 5000)
    def test_non_darwin_unchanged(self):
        for system in ("Linux", "Windows"):
            self.assertEqual(self.s.resolve_web_port(system, "5100", 5200), 5000)
    def test_step_clamps(self):
        st = self.s.step_web_port
        self.assertEqual(st(5000, 1), 5001)
        self.assertEqual(st(5000, -100), 4900)
        self.assertEqual(st(1024, -1), 1024)
        self.assertEqual(st(1050, -100), 1024)
        self.assertEqual(st(65535, 1), 65535)
        self.assertEqual(st(65500, 100), 65535)
        self.assertEqual(st(None, 1), 5001)
    def test_default_setting_darwin_only(self):
        code = ("import platform, sys, json;platform.system = lambda: %r;sys.path.insert(0, %r);"
                "import rgsx_settings as s;print(json.dumps(s.load_rgsx_settings().get('web_port')))")
        for system, expected in (("Darwin", 5000), ("Linux", None), ("Windows", None)):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as home:
                env = dict(os.environ, HOME=home, RGSX_HEADLESS="1", RGSX_CONFIG_DIR=os.path.join(home, "cfg"))
                out = subprocess.run([sys.executable, "-c", code % (system, APP)], env=env,
                                     capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), expected)
    def test_set_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config, "SAVE_FOLDER", d), \
                 mock.patch.object(config, "RGSX_SETTINGS_PATH", os.path.join(d, "rgsx_settings.json")):
                self.assertEqual(self.s.set_web_port(5077), 5077)
                self.assertEqual(self.s.get_web_port(), 5077)
                self.assertEqual(self.s.set_web_port(80), 1024)
                self.assertEqual(self.s.set_web_port(99999), 65535)
                self.assertEqual(self.s.set_web_port("5088"), 5088)
                self.assertIsNone(self.s.set_web_port("abc"))
                self.assertIsNone(self.s.set_web_port(True))
                self.assertEqual(self.s.get_web_port(), 5088)
                self.assertTrue(self.s.set_web_host("0.0.0.0"))
                self.assertEqual(self.s.get_web_host(), "0.0.0.0")
                self.assertFalse(self.s.set_web_host("evil"))
                self.assertEqual(self.s.get_web_host(), "0.0.0.0")
                with open(os.path.join(d, "rgsx_settings.json"), encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual((saved["web_host"], saved["web_port"]), ("0.0.0.0", 5088))
    def test_invalid_saved_port_gives_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rgsx_settings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"web_port": "nope"}, f)
            with mock.patch.object(config, "SAVE_FOLDER", d), mock.patch.object(config, "RGSX_SETTINGS_PATH", path):
                self.assertEqual(self.s.get_web_port(), 5000)
    def test_network_access_and_urls(self):
        self.assertFalse(self.s.is_network_access("127.0.0.1"))
        self.assertTrue(self.s.is_network_access("0.0.0.0"))
        self.assertFalse(self.s.is_network_access("bogus"))
        self.assertEqual(self.s.web_urls("127.0.0.1", 5001, "192.168.1.83"), ["http://localhost:5001"])
        self.assertEqual(self.s.web_urls("0.0.0.0", 5001, "192.168.1.83"),
                         ["http://localhost:5001", "http://192.168.1.83:5001"])
        self.assertEqual(self.s.web_urls("0.0.0.0", 5001, None), ["http://localhost:5001"])
    def test_port_note_lines(self):
        self.assertEqual(self.s.web_port_note_lines(5000, 5000), [])
        lines = self.s.web_port_note_lines(5000, 5001)
        self.assertEqual(lines[0][0], "warning")
        self.assertIn("5000", lines[0][1])
        self.assertIn("5001", lines[0][1])
    def test_pick_free_port_busy_fallback(self):
        import socket
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            busy = blocker.getsockname()[1]
            picked = self.s.pick_free_port("127.0.0.1", busy)
            self.assertNotEqual(picked, busy)
            self.assertGreater(picked, 0)
        finally:
            blocker.close()
    def test_pick_free_port_top_of_range(self):
        picked = self.s.pick_free_port("127.0.0.1", 65535)
        self.assertTrue(1 <= picked <= 65535)
class WebSettingsMenuRows(unittest.TestCase):
    """Settings menu rows: Darwin adds two rows, other systems keep the historical layout."""
    def _options(self, system, selected=0):
        import display
        captured = {}
        with mock.patch.object(config, "OPERATING_SYSTEM", system), \
             mock.patch.object(display, "_draw_submenu_generic", lambda *a, **k: captured.update(args=a)), \
             mock.patch.object(display, "check_web_service_status", lambda: False, create=True), \
             mock.patch.object(display, "check_custom_dns_status", lambda: False, create=True):
            display.draw_pause_settings_menu(None, selected)
        return captured["args"]
    def test_row_counts(self):
        self.assertEqual(len(self._options("Windows")[2]), 8)
        self.assertEqual(len(self._options("Linux")[2]), 10)
        self.assertEqual(len(self._options("Darwin")[2]), 10)
    def test_darwin_rows(self):
        opts = self._options("Darwin")[2]
        self.assertIn("< This Mac only >", opts[5])
        self.assertIn("< 5000 >", opts[6])
        for text in self._options("Windows")[2] + self._options("Linux")[2]:
            self.assertNotIn("Web interface", text)
    def test_darwin_instruction_has_url(self):
        with mock.patch.object(config, "web_runtime", {"host": "0.0.0.0", "port": 5077, "requested_port": 5000}, create=True):
            instruction = self._options("Darwin", 6)[4]
        self.assertIn("http://localhost:5077", instruction)
        self.assertIn("5000", instruction)
def tearDownModule():
    shutil.rmtree(_TMP_HOME, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
