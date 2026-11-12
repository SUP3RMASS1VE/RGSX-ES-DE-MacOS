"""Selective upstream backport: isolated disk fixtures, no external network or real user data."""
import asyncio
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("RGSX_HEADLESS", "1")
_IMPORT_HOME = tempfile.TemporaryDirectory(prefix="rgsx_integration_home_")
os.environ["HOME"] = _IMPORT_HOME.name
APP = Path(__file__).resolve().parents[1] / "ports" / "RGSX"
sys.path.insert(0, str(APP))

import config
import database
import history
import media_manager
import network
import rgsx_settings
import rgsx_web
import screenscraper
import utils


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rgsx_integration_test_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = self.root / "rgsx_settings.json"
        paths = {name: str(self.root / filename) for name, filename in {
            "RGSX_SETTINGS_PATH": "rgsx_settings.json", "DB_PATH": "rgsx.sqlite3",
            "HISTORY_PATH": "history.json", "DOWNLOADED_GAMES_PATH": "downloaded_games.json",
            "MEDIA_FOLDER": "media", "MEDIA_QUEUE_PATH": "media_queue.json",
            "SCREENSCRAPER_ACCOUNT_PATH": "screenscraper_account.json", "ROMS_FOLDER": "roms",
        }.items()}
        self.addCleanup(mock.patch.stopall)
        mock.patch.multiple(config, **paths, SAVE_FOLDER=str(self.root), CONFIG_FOLDER=str(self.root),
                            OPERATING_SYSTEM="Darwin", history=[], download_queue=[], download_progress={},
                            download_active=False, active_download_count=0, max_simultaneous_downloads=1).start()
        mock.patch.object(network.requests, "get", side_effect=AssertionError("external network is forbidden")).start()


class ArchiveSafetyTests(IsolatedCase):
    def archive(self, members):
        path = self.root / "download.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in members:
                archive.writestr(name, content)
        return path

    def extract(self, path):
        return utils.extract_zip(str(path), str(self.root / "games"), "fixture://download")

    def test_traversal_is_rejected_before_any_file_is_written(self):
        path = self.archive([("good.rom", "good"), ("../outside.rom", "bad")])
        self.assertFalse(self.extract(path)[0])
        self.assertFalse((self.root / "outside.rom").exists())
        self.assertFalse((self.root / "games/good.rom").exists())
        self.assertTrue(path.exists())

    def test_absolute_path_is_rejected(self):
        target = self.root / "outside.rom"
        path = self.archive([(str(target), "bad")])
        self.assertFalse(self.extract(path)[0])
        self.assertFalse(target.exists())

    def test_symlink_outside_game_folder_is_rejected(self):
        (self.root / "games").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "games/link").symlink_to(self.root / "outside", target_is_directory=True)
        path = self.archive([("link/save.dat", "bad")])
        self.assertFalse(self.extract(path)[0])
        self.assertFalse((self.root / "outside/save.dat").exists())

    def test_nonempty_folder_and_its_save_are_preserved(self):
        save = self.root / "games/Game/save.dat"
        save.parent.mkdir(parents=True)
        save.write_text("existing save")
        path = self.archive([("Game", "replacement")])
        self.assertFalse(self.extract(path)[0])
        self.assertEqual(save.read_text(), "existing save")

    def test_successful_zip_extracts_normally(self):
        path = self.archive([("Game/game.rom", "valid rom")])
        with mock.patch.object(utils, "_handle_special_platforms", return_value=(True, None)):
            self.assertTrue(self.extract(path)[0])
        self.assertEqual((self.root / "games/Game/game.rom").read_text(), "valid rom")

    def test_low_space_keeps_archive_and_existing_files(self):
        save = self.root / "games/save.dat"
        save.parent.mkdir()
        save.write_text("save")
        path = self.archive([("game.rom", "rom")])
        with mock.patch.object(utils, "_check_room_for_extraction", return_value="not enough space"):
            ok, message = self.extract(path)
        self.assertFalse(ok)
        self.assertEqual(message, "not enough space")
        self.assertEqual(save.read_text(), "save")
        self.assertTrue(path.exists())

    def test_arcade_romsets_remain_zipped_without_system_list(self):
        with mock.patch.object(utils, "load_extensions_json", return_value=[]), \
                mock.patch.object(utils, "_get_dest_folder_name", return_value="mame"), \
                mock.patch.object(utils, "_get_rgsx_folder_name", return_value="mame"), \
                mock.patch.object(config, "platform_dicts", []):
            result = utils.check_extension_before_download("https://example.test/game.zip", "MAME", "game.zip")
        self.assertFalse(result[3])


class SettingsSaveTests(IsolatedCase):
    def test_failed_atomic_replace_keeps_original_and_cleans_temporary_file(self):
        self.settings.write_text('{"web_port": 5077, "custom": "keep"}')
        before = self.settings.read_bytes()
        with mock.patch.object(rgsx_settings.os, "replace", side_effect=OSError(5, "disk failure")):
            self.assertFalse(rgsx_settings.save_rgsx_settings({"web_port": 5088}))
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_atomic_save_keeps_permissions_and_custom_mac_settings(self):
        saved = {"web_host": "127.0.0.1", "web_port": 5077, "rom_folder_map": {"gamecube": "gc"},
                 "display": {"fullscreen": False, "background_theme": "midnight"}, "custom": {"keep": 1}}
        self.settings.write_text(json.dumps(saved))
        self.settings.chmod(0o600)
        settings = rgsx_settings.load_rgsx_settings()
        settings["screenscraper_disabled"] = True
        self.assertTrue(rgsx_settings.save_rgsx_settings(settings))
        actual = json.loads(self.settings.read_text())
        for key, value in saved.items():
            self.assertEqual(actual[key], value)
        self.assertEqual(stat.S_IMODE(self.settings.stat().st_mode), 0o600)

    def test_corrupt_settings_are_retained_for_recovery(self):
        self.settings.write_text('{"broken"')
        rgsx_settings.load_rgsx_settings()
        self.assertEqual(Path(str(self.settings) + ".bad").read_text(), '{"broken"')


class HistoryResumeTests(IsolatedCase):
    def test_reload_keeps_every_running_row_and_its_object(self):
        live = {"url": "fixture://live", "task_id": "live", "status": "Downloading"}
        config.history = [live]
        stored = [{"url": "fixture://old", "status": "Download_OK"},
                  {"url": "fixture://live", "task_id": "live", "status": "Queued"}]
        with mock.patch.object(history, "load_history", return_value=stored):
            history.reload_history({"live": object()})
        self.assertEqual(len(config.history), 2)
        self.assertIs(config.history[1], live)

    def test_new_running_row_survives_reload_before_first_save(self):
        live = {"url": "fixture://live", "task_id": "live"}
        config.history = [live]
        with mock.patch.object(history, "load_history", return_value=[]):
            history.reload_history(["live"])
        self.assertEqual(config.history, [live])

    def test_restart_queues_recent_interrupted_downloads_in_order(self):
        now = datetime.now()
        entries = [{"platform": "NES", "game_name": name, "url": "fixture://" + name, "status": status,
                    "timestamp": (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")}
                   for name, status, minutes in [("second", "Extracting", 1), ("first", "Queued", 2),
                                                  ("done", "Download_OK", 3), ("ancient", "Downloading", 12000)]]
        with mock.patch.object(history, "load_history", return_value=entries), \
                mock.patch.object(utils, "check_extension_before_download", return_value=(None, None, None, True)), \
                mock.patch.object(utils, "save_history", return_value=True):
            self.assertEqual(utils.queue_interrupted_downloads(), 2)
        self.assertEqual([row["game_name"] for row in config.download_queue], ["first", "second"])
        self.assertTrue(all(row["is_zip_non_supported"] for row in config.download_queue))
        self.assertEqual(entries[-1]["status"], "Erreur")


class MediaManagerTests(IsolatedCase):
    def test_artwork_is_saved_and_found_in_mac_cache(self):
        path = Path(media_manager.save_media("gc", "Game.iso", "box", (b"image fixture", ".jpg")))
        self.assertTrue(path.is_relative_to(self.root / "media"))
        self.assertEqual(path.read_bytes(), b"image fixture")
        self.assertEqual(media_manager.find_media("gc", "Game.iso"), str(path))

    def test_media_names_cannot_escape_cache(self):
        path = Path(media_manager.save_media("../../outside", "../../Game.iso", "ss", (b"image", ".jpg")))
        self.assertTrue(path.resolve().is_relative_to((self.root / "media").resolve()))

    def test_queue_survives_restart(self):
        rows = [{"folder": "gc", "rom_filename": "Game.iso", "platform_name": "GameCube", "attempts": 0}]
        media_manager.save_queue("max", rows, [])
        queue = media_manager.load_queue()
        self.assertEqual(queue["profile"], "max")
        self.assertEqual(queue["items"], rows)

    def test_native_and_web_media_jobs_cannot_run_simultaneously(self):
        lock = media_manager.acquire_media_job_lock()
        try:
            self.assertIsNotNone(lock)
            self.assertTrue(media_manager.media_job_running_elsewhere())
        finally:
            lock.close()
        self.assertFalse(media_manager.media_job_running_elsewhere())

    def test_grouped_sources_share_one_media_selection(self):
        entries = [{"platform_name": "GameCube A", "folder": "gamecube"},
                   {"platform_name": "GameCube B", "folder": "gamecube"}]
        with mock.patch.object(config, "platform_dicts", entries), \
                mock.patch.object(database, "list_game_counts", return_value={"GameCube A": 2, "GameCube B": 3}), \
                mock.patch.object(screenscraper, "get_configured_system_id", return_value=13):
            groups = media_manager.MediaManager().list_platforms()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 5)
        self.assertEqual(groups[0]["platform_id"], 13)

    def test_schema_upgrade_keeps_existing_history(self):
        database.initialize_database(config.DB_PATH)
        existing = [{"platform": "GameCube", "game_name": "Game.iso", "url": "fixture://game", "status": "Download_OK"}]
        database.save_history(existing, config.DB_PATH)
        with sqlite3.connect(config.DB_PATH) as db:
            db.execute("ALTER TABLE platforms DROP COLUMN screenscraper_system_id")
            db.execute("DROP TABLE screenscraper_game_summaries")
            db.execute("DROP TABLE screenscraper_systems")
        database.initialize_database(config.DB_PATH)
        self.assertEqual(database.load_history(config.DB_PATH)[0]["game_name"], "Game.iso")
        database.save_game_summary(13, "Game.iso", "Summary", True, db_path=config.DB_PATH)
        self.assertEqual(database.load_game_summary(13, "Game.iso", config.DB_PATH)["summary"], "Summary")


class WebIntegrationTests(IsolatedCase):
    def post(self, route, data):
        handler = rgsx_web.RGSXHandler.__new__(rgsx_web.RGSXHandler)
        body = json.dumps(data).encode()
        handler.path = route
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler._send_json = mock.Mock()
        handler.do_POST()
        return handler._send_json.call_args

    def test_download_uses_clicked_name_and_url_after_catalog_reorder(self):
        games = [config.Game("Other.zip", "fixture://other", None, "Other"),
                 config.Game("Wanted.zip", "fixture://wanted", None, "Wanted")]
        with mock.patch.object(rgsx_web, "get_cached_games", return_value=(games, None, None)), \
                mock.patch.object(utils, "check_extension_before_download", return_value=(None, None, None, False)), \
                mock.patch.object(rgsx_web, "reload_history"), mock.patch.object(rgsx_web, "save_history", return_value=True):
            config.active_download_count = 1
            result = self.post("/api/download", {"platform": "NES", "game_index": 0, "game_name": "Wanted.zip",
                                                   "game_url": "fixture://wanted", "mode": "now"})
        self.assertTrue(result.args[0]["success"])
        self.assertEqual(config.download_queue[0]["url"], "fixture://wanted")

    def test_web_settings_preserve_mac_options_and_unknown_keys(self):
        saved = {"web_host": "127.0.0.1", "web_port": 5077, "esde_folder_mapping": True,
                 "custom": "keep", "display": {"fullscreen": False, "grid": "4x4"}}
        self.settings.write_text(json.dumps(saved))
        result = self.post("/api/settings", {"settings": {"display": {"cover_preview": True}}})
        self.assertTrue(result.args[0]["success"])
        actual = json.loads(self.settings.read_text())
        self.assertEqual(actual["web_port"], 5077)
        self.assertEqual(actual["display"], {**saved["display"], "cover_preview": True})
        self.assertEqual(actual["custom"], "keep")

    def test_media_start_rejects_missing_account(self):
        manager = media_manager.MediaManager()
        with mock.patch.object(rgsx_web, "_get_web_media_manager", return_value=manager):
            result = self.post("/api/media/start", {"folders": ["gc"], "profile": "default"})
        self.assertEqual(result.kwargs["status"], 400)
        self.assertEqual(result.args[0]["error"], "media_account_required")

    def test_saving_credentials_refreshes_an_open_idle_media_manager(self):
        manager = mock.Mock(running=False)
        with mock.patch.object(rgsx_web, "_web_media_manager", manager), \
                mock.patch.object(screenscraper, "load_account", return_value=("", "")), \
                mock.patch.object(screenscraper, "save_account") as save, \
                mock.patch.object(screenscraper, "get_user_info", return_value={}):
            result = self.post("/api/settings", {"settings": {"screenscraper": {"username": "fixture", "password": "fixture"}}})
        self.assertTrue(result.args[0]["success"])
        save.assert_called_once_with("fixture", "fixture")
        manager.open.assert_called_once_with()

    def test_media_start_honours_scraper_disabled_setting(self):
        self.settings.write_text('{"screenscraper_disabled": true}')
        with mock.patch.object(rgsx_web, "_get_web_media_manager", return_value=media_manager.MediaManager()):
            result = self.post("/api/media/start", {"folders": ["gc"], "profile": "default"})
        self.assertEqual(result.kwargs["status"], 403)

    def test_every_update_package_is_refused_on_macos(self):
        archive = self.root / "update.zip"
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr("config.py", "replace the port")
        for url in (config.OTA_UPDATE_ZIP, config.FORK_UPDATE_ZIP, "file:///update.zip"):
            with self.subTest(url=url):
                destination = self.root / "app"
                self.assertFalse(network.extract_update(str(archive), str(destination), url)[0])
                self.assertFalse(destination.exists())
        self.assertTrue(asyncio.run(network.apply_pending_update("9.9.9"))[0])
        self.assertFalse((self.root / "app").exists())


if __name__ == "__main__":
    unittest.main()
