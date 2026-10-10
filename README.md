# 🎮 RGSX for macOS (ES-DE, Apple Silicon)

**[Installation](#-installation)** • **[Troubleshooting](#%EF%B8%8F-troubleshooting)** • **[French Documentation](README_FR.md)** • **[Issues](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/issues)** • **[Upstream project](https://github.com/RetroGameSets/RGSX)**

A free, user-friendly ROM downloader that runs inside [ES-DE](https://es-de.org) (EmulationStation Desktop Edition) on Apple Silicon Macs, with multi-source support.

This repository is a **macOS-only fork** of [RetroGameSets/RGSX](https://github.com/RetroGameSets/RGSX) (Retro Game Sets Xtra), the ROM downloader for Batocera, Knulli and RetroBat. All credit for RGSX itself goes to the upstream authors and contributors. This fork only contains the macOS (Apple Silicon, arm64) port that is launched from ES-DE. For Batocera, Knulli, RetroBat or Docker, use the [upstream project](https://github.com/RetroGameSets/RGSX).

<p align="center">
  <img width="69%" alt="main" src="https://github.com/user-attachments/assets/a98f1189-9a50-4cc3-b588-3f85245640d8" />
  <img width="30%" alt="controls help" src="https://github.com/user-attachments/assets/38cac7e6-14f2-4e83-91da-0679669822ee" />
</p>
<p align="center"><sub>Screenshots from the upstream project.</sub></p>

---

## 🚀 Installation

Nothing to install: no Homebrew, no terminal, no Python. RGSX downloads what it needs on first launch.

1. Download the zip from this fork's [releases](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/releases/latest) (`RGSX_macos_arm64.zip`) and unzip it. Or clone the repo: `git clone https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS.git`.
2. Move the `ports` folder into your ES-DE ROMs folder (default `~/ES-DE/ROMs`). Any ROMs folder works as long as RGSX ends up in `<ROMs>/ports/RGSX`. If you already have an older `ports/RGSX`, replace it instead of merging into it.
3. In ES-DE open **Ports > RGSX**.
4. First launch only: RGSX downloads about 60 MB. Expect a few minutes depending on your connection. A Terminal window with the progress and a small dialog appear; a blank screen for a moment is normal. Keep the Mac online. Later launches start in a couple of seconds and work offline.
   - A leftover Terminal window after setup is normal and can be closed.
   - ES-DE may run the script with `/bin/sh`, bash or zsh; the launcher works with all of them.
   - Optional artwork: copy `ports/gamelist.xml` and `ports/images` to `~/ES-DE/gamelists/ports` and `~/ES-DE/downloaded_media` (RGSX never writes into `~/ES-DE`).

### What RGSX sets up automatically

On first launch, into `~/Library/Application Support/RGSX/runtime` (about 200 MB):

- A pinned Python 3.12 runtime (arm64)
- The Python packages RGSX needs (hash-locked)
- libtorrent, for torrent sources
- 7-Zip (`7zz`), for archives including RAR

The runtime survives replacing the `ports` folder, so updating does not download it again.

### Where things live

- Settings, logs, controls, history, API keys: `~/Library/Application Support/RGSX`
- Logs: `~/Library/Application Support/RGSX/logs/` (`bootstrap.log` for setup, `RGSX.log` for the app)
- Runtime (Python, libraries, 7-Zip): `~/Library/Application Support/RGSX/runtime`
- ROMs: the folder that contains `ports` (`<ROMs>/ports/RGSX/RGSX.sh` gives `<ROMs>`), so downloads land where ES-DE looks. If RGSX is not inside a `ports` folder it falls back to `~/ROMs` if that exists, otherwise `~/Documents/RGSX/roms`.
- Overrides, highest priority first: the `roms_folder` setting in `rgsx_settings.json`, the `RGSX_ROMS_DIR` environment variable, the folder derived from where RGSX lives, then the defaults above.

### Updating

Replace the `ports` folder with the new one (delete the old `ports/RGSX` first rather than merging). Settings and the runtime live outside it and are kept.

### ES-DE folder names

RGSX uses Batocera/RetroBat folder names, ES-DE uses its own. RGSX translates them on macOS so games land in the folders ES-DE scans:

| RGSX | ES-DE | RGSX | ES-DE |
|---|---|---|---|
| `3ds` | `n3ds` | `lynx` | `atarilynx` |
| `amiga500` | `amiga` | `MSX2+ (Archive)` | `msx2` |
| `amigacdtv` | `cdtv` | `o2em` | `odyssey2` |
| `c20` | `vic20` | `sg1000` | `sg-1000` |
| `cplus4` | `plus4` | `wswan` | `wonderswan` |
| `cdi` | `cdimono1` | `wswanc` | `wonderswancolor` |
| `gamecube` | `gc` | `jaguar` | `atarijaguar` |

- Other systems already use the same name.
- Systems ES-DE does not have (`advision`, `atom`, `chihiro`, `lindbergh`, `namco2x6`, `pico`, `teknoparrot`) keep the RGSX name and need a custom ES-DE system to show up.
- In `rgsx_settings.json`, `"esde_folder_mapping": false` turns the translation off. `"rom_folder_map": {"gamecube": "gc", "pico": "segapico"}` adds or overrides entries (a value equal to the key disables that default).
- Games already downloaded under an old RGSX name (for example `gamecube`) are not detected after the change. Move them to the ES-DE folder yourself; nothing is moved automatically.

### Requirements

- Apple Silicon Mac (M1 or newer). Intel Macs are not supported: the launcher stops with a message.
- ES-DE for macOS.
- Internet on the first launch (about 60 MB). Later launches work offline, except for downloading games.
- Torrent sources need macOS 14 (Sonoma) or newer. On macOS 11 to 13 everything else works and torrents are disabled with a clear message.

---

## 🎮 Usage

### First Launch

- Auto-downloads system images and game lists
- All game systems are listed, since there is no EmulationStation config to define the supported ones here
- Windowed by default (toggle in Settings > Display mode)

### Controls

**Keyboard** (when no controller is detected, controls display as `[Key]` instead of icons):

| Action | Key |
|---|---|
| Confirm / Cancel | `Enter` / `Esc` |
| Navigate | Arrow keys |
| Start (pause menu) | `P` |
| Filter | `F` |
| History | `H` |
| Clear history | `X` |
| Page up / down | `Fn+↑` / `Fn+↓` |
| Delete | `Backspace` |
| Space | `Space` |

Controllers are auto-mapped when recognized, and you can remap them from the pause menu. **Controls broken?** Delete `~/Library/Application Support/RGSX/controls.json` and restart.

### Pause Menu Structure

**Root categories**
- Games (downloads, scans, platform visibility)
- Language (switch UI language)
- Controls (help and remap)
- Display (layout, fonts, monitor/mode, visual options)
- Settings (music, symlink, auto extract, network and API status)
- Support (generate support ZIP/log bundle)
- Quit (exit or restart)

**Controls**
- View Controls Help (shows current mapped actions)
- Remap Controls (reconfigure keyboard/controller mapping)

**Display**
- Layout (3×3, 3×4, 4×3, 4×4)
- Font Size submenu (general UI + footer text)
- Font Family (Pixel or DejaVu)
- Monitor selection (when multiple monitors are detected)
- Light Mode (performance-friendly rendering)
- Hide Unknown Extension Warning (toggle unsupported extension warnings)

**Games**
- Update Game Cache (redownload systems/games data)
- Scan Owned ROMs (add locally owned ROMs to history)
- Download History (view/manage download entries)
- Show Unsupported Platforms (toggle platforms without local ROM folders)
- Filter Platforms (source/platform visibility menu)

**Settings**
- Background Music Toggle (enable/disable music)
- Symlink Options (choose copy/symlink behavior)
- Auto Extract Toggle (automatic archive extraction)
- ROMs Folder Selector (set custom ROM root folder)
- API Keys Status (check provider key presence)
- Connection Status (test required updates/sources sites)

---

## ✨ Features

- 📦 **Intelligent Archive Handling** – Auto-extracts archives when systems don't support ZIP files (RAR via the bundled 7-Zip)
- 🔑 **Premium Unlocking** – 1Fichier API + AllDebrid/Debrid-Link/Real-Debrid/TorBox fallback for unlimited downloads
- 🎨 **Fully Customizable** – Layout (3×3 to 4×4), fonts, font sizes (UI + footer), languages (EN/FR/DE/ES/IT/PT)
- 🎮 **Controller-First Design** – Auto-mapping for popular controllers + custom remapping support
- 🧲 **Torrent sources** – Built-in libtorrent, no extra app needed
- 🔍 **Advanced Filtering** – Search by name, hide/show unsupported systems, filter platforms
- 📊 **Download Management** – Queue system, history tracking, progress notifications
- ♿ **Accessibility** – Separate font scaling for UI and footer, keyboard-only mode support

> ### 🔑 API Keys Setup
> For unlimited 1Fichier downloads, add your API key(s) to `~/Library/Application Support/RGSX/`:
> - `1FichierAPI.txt` – 1Fichier API key (recommended)
> - `AllDebridAPI.txt` – AllDebrid fallback (optional)
> - `DebridLinkAPI.txt` – Debrid-Link fallback (optional)
> - `RealDebridAPI.txt` – Real-Debrid fallback (optional)
> - `TorBoxAPI.txt` – TorBox fallback (optional)
>
> **Each file must contain ONLY the key, no extra text.**

### Downloading Games

1. Browse platforms → Select game
2. **Direct Download**: Press `Confirm`
3. **Queue Download**: Press `X` (West button)
4. Track progress in **History** menu or via popup notifications

### Torrents

Torrent sources run through libtorrent, installed automatically on macOS 14 or newer.

- Seeding only happens while RGSX is open.
- On the first torrent the macOS firewall may ask about incoming connections. Choosing Deny still allows downloading.
- To never get that prompt, set `RGSX_TORRENT_LISTEN=off`: RGSX then listens on loopback only and disables DHT, LSD and UPnP.
- When seeding across volumes, a second copy of the file is kept until RGSX exits.

---

## 🌐 Web Interface

RGSX starts a small web interface for browsing and downloading from a browser.

- Local only by default: `http://localhost:5000`, or the next free port up to 5010. macOS AirPlay Receiver uses port 5000 and RGSX never stops it, so you will often get `5001`.
- The chosen port is written to `~/Library/Application Support/RGSX/web_port.txt` and logged.
- `RGSX_OPEN_WEB=1` opens it in your browser at launch.
- `RGSX_WEB_HOST=0.0.0.0` exposes it on your network (takes precedence over the setting below). There is no authentication, so only do this on a network you trust.

To open it from a phone or another computer on your network (ES-DE cannot set environment variables, so use the setting):

1. Quit RGSX and edit `~/Library/Application Support/RGSX/rgsx_settings.json`: set `"web_host": "0.0.0.0"` (the default is `"127.0.0.1"`, this Mac only).
2. Start RGSX again (a restart is required).
3. Open `http://<your Mac's LAN IP>:<port>` in a browser. The port is in `~/Library/Application Support/RGSX/web_port.txt` and in the log (5000, or 5001 if AirPlay Receiver holds 5000).
4. macOS may ask whether to allow incoming connections: allow it.

There is no login. Anyone on the same network can use the interface, so only enable this on networks you trust. RGSX logs a WARNING when it is exposed.

---

## 🛠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| Nothing happens / macOS blocks the files | Run `xattr -dr com.apple.quarantine <ports folder>` in Terminal (the launcher also tries this itself), then launch again. |
| First launch seems stuck | The first launch downloads about 60 MB. Wait a few minutes and keep the Mac online. Check `~/Library/Application Support/RGSX/logs/bootstrap.log`. |
| Setup error naming a host | The message names the host that could not be reached (github.com for Python, www.7-zip.org for 7-Zip, pypi.org / files.pythonhosted.org for libraries). Check your connection, VPN or firewall and launch again. |
| "RGSX is incomplete" dialog | Re-copy the whole `ports` folder (replace the old one, do not merge). |
| Two RGSX entries in ES-DE | An old install is still in `<ROMs>/ports`. Delete the old `RGSX` folder and any old launcher scripts, then copy the new `ports` folder. |
| Web interface not on port 5000 | AirPlay Receiver owns 5000. RGSX uses the next free port (usually 5001). See `~/Library/Application Support/RGSX/web_port.txt`. |
| Firewall prompt on first torrent | Deny still allows downloading. Set `RGSX_TORRENT_LISTEN=off` to never get the prompt. |
| Torrents disabled | They need macOS 14 or newer. |
| 7-Zip is missing | Launch RGSX again with internet, it repairs itself. See `logs/bootstrap.log`. |
| Python or 7zz does not start | Run `xattr -dr com.apple.quarantine ~/Library/Application\ Support/RGSX/runtime` and launch again. |
| Reset the runtime | Delete `~/Library/Application Support/RGSX/runtime`; the next launch downloads it again. |
| Controls not working | Delete `~/Library/Application Support/RGSX/controls.json` and restart the app. |
| No games? | Pause Menu > Games > Update Game Cache, then check Filter Platforms and Show Unsupported Platforms. In `rgsx_settings.json`, make sure `sources` > `mode` is `rgsx` and not `custom`. |
| App crashes | Check `~/Library/Application Support/RGSX/logs/RGSX.log`. |
| Layout change not applied | Restart RGSX after changing layout. |
| Problem downloading some games | Open Pause Menu > Settings > Connection Status. If required sites are red, check your network, VPN, DNS and router protections. |

---

## ⚠️ Limitations

- Apple Silicon only. Intel Macs are not supported.
- PS3 and Xbox conversions (`ps3dec`, `xdvdfs`, `extract-xiso`) are not supported; those downloads are kept as archives.
- Batocera-only features (boot services, custom DNS) are hidden.
- Not verified on real hardware by the fork author: a Gatekeeper block on a second Mac, and controller input on macOS (keyboard is tested).

---

## 🤝 Contributing

- **Bug reports / feature requests for this macOS fork**: open an [issue](https://github.com/SUP3RMASS1VE/RGSX-ES-DE-MacOS/issues) with the logs from `~/Library/Application Support/RGSX/logs/`.
- Issues about Batocera, Knulli, RetroBat or the core app belong to the [upstream project](https://github.com/RetroGameSets/RGSX) (upstream Discord: [discord.gg/XPK8YG8XYC](https://discord.gg/XPK8YG8XYC)).

---

## 📝 License and credits

RGSX is created by [RetroGameSets](https://github.com/RetroGameSets/RGSX). Upstream describes it as free and open-source software that you can use, modify and distribute freely, and this fork follows the same terms. No separate LICENSE file is present in this repository.

Thanks to all [upstream contributors](https://github.com/RetroGameSets/RGSX/graphs/contributors) and followers of the app.

**Developed with ❤️ for the retro gaming community.**
