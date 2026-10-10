"""macOS only: map RGSX ROM folder names to the folder names ES-DE scans.

RGSX uses Batocera/RetroBat folder names; ES-DE uses its own. On Darwin the
download/scan directory is built with map_rom_folder(); on every other OS the
function is the identity, so Windows/Linux/Batocera behavior is unchanged.

Optional rgsx_settings.json keys (read directly, no import of rgsx_settings):
  - "esde_folder_mapping": false         -> disable the mapping entirely
  - "rom_folder_map": {"gamecube": "gc"} -> overrides/additions; a value equal to
                                            the key disables that default mapping
"""
import json
import logging
import os
import platform

import config

logger = logging.getLogger(__name__)

# RGSX folder -> ES-DE folder (verified against ES-DE's macOS es_systems.xml).
# "bios" is deliberately absent (archive extraction logic tests for "bios").
ESDE_FOLDER_MAP = {
    "3ds": "n3ds",
    "amiga500": "amiga",
    "amigacdtv": "cdtv",
    "c20": "vic20",
    "cplus4": "plus4",
    "cdi": "cdimono1",
    "gamecube": "gc",
    "jaguar": "atarijaguar",
    "lynx": "atarilynx",
    "MSX2+ (Archive)": "msx2",
    "o2em": "odyssey2",
    "sg1000": "sg-1000",
    "wswan": "wonderswan",
    "wswanc": "wonderswancolor",
}

_cache = None


def _reset_cache():
    global _cache
    _cache = None


def _load_effective_map():
    """Return the effective mapping (defaults + user overlay), cached."""
    global _cache
    if _cache is not None:
        return _cache
    effective = dict(ESDE_FOLDER_MAP)
    try:
        path = os.path.join(config.SAVE_FOLDER, "rgsx_settings.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if isinstance(settings, dict):
                if settings.get("esde_folder_mapping") is False:
                    effective = {}
                overlay = settings.get("rom_folder_map")
                if isinstance(overlay, dict):
                    for key, value in overlay.items():
                        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
                            continue
                        if value == key:
                            effective.pop(key, None)
                        else:
                            effective[key] = value.strip()
    except Exception as e:
        logger.debug(f"esde_folders: settings ignored ({e})")
        effective = dict(ESDE_FOLDER_MAP)
    _cache = effective
    return _cache


def map_rom_folder(folder):
    """Return the ES-DE folder name on macOS, `folder` unchanged elsewhere."""
    if not folder or platform.system() != "Darwin":
        return folder
    return _load_effective_map().get(folder, folder)
