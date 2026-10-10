# 🎮 Retro Game Sets Xtra (RGSX)

**[Discord Support](https://discord.gg/XPK8YG8XYC)** • **[Installation](#-installation)** • **[French Documentation](https://github.com/RetroGameSets/RGSX/blob/main/README_FR.md)** • **[Troubleshoot / Common Errors](https://github.com/RetroGameSets/RGSX#%EF%B8%8F-troubleshooting)** •

A free, user-friendly ROM downloader for Batocera, Knulli, RetroBat, and macOS (Apple Silicon) with multi-source support.

<p align="center">
  <img width="69%" alt="main" src="https://github.com/user-attachments/assets/a98f1189-9a50-4cc3-b588-3f85245640d8" />
  <img width="30%" alt="controls help" src="https://github.com/user-attachments/assets/38cac7e6-14f2-4e83-91da-0679669822ee" />
</p>
<p align="center">
  <img width="49%" alt="web interface" src="https://github.com/user-attachments/assets/71f8bd39-5901-45a9-82b2-91426b3c31a7" />
  <img width="49%" alt="api menu" src="https://github.com/user-attachments/assets/5bae018d-b7d9-4a95-9f1b-77db751ff24f" />
</p>


---

## 🚀 Installation

### Quick Install (Batocera / Knulli)

**SSH or Terminal access required:**
```bash
curl -L bit.ly/rgsx-install | sh
```

After installation:
1. Update game lists: `Menu > Game Settings > Update game list`
2. Find RGSX under **PORTS** or **Homebrew and ports**

### Manual Install (All Systems)
1. **Download**: [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)
2. **Extract**:
   - **Batocera/Knulli**: Extract `ports` folder to `/roms/`
   - **RetroBat**: Extract both `ports` and `windows` folders to `/roms/`
3. **Refresh**: `Menu > Game Settings > Update game list`

### macOS (Apple Silicon)
Native run from source on M-series Macs (Python + pygame, no EmulationStation needed).
1. **Prerequisites** ([Homebrew](https://brew.sh)): `brew install python@3.12 sevenzip` (optional: `brew install unar`). Python 3.10 to 3.13 is required.
2. **Get the code**: download `RGSX_macos_arm64.zip` from the [releases](https://github.com/RetroGameSets/RGSX/releases/latest), or clone this repository.
3. **Run**: `cd ports/RGSX && ./run_macos.sh` (creates a virtual environment and installs dependencies on first launch).
   - `--open-web`: open the web interface in your browser once it is up
   - `--reinstall`: recreate the virtual environment
4. **First run notes**: if macOS blocks the files, run `xattr -dr com.apple.quarantine <RGSX folder>`. macOS may ask permission to access `~/Documents`.

**Where things live:**
- Settings, logs, controls, history: `~/Library/Application Support/RGSX`
- ROMs: `~/ROMs` if that folder exists (ES-DE's default ROM root), otherwise `~/Documents/RGSX/roms`
- Overrides, highest priority first: the `roms_folder` setting, then the `RGSX_CONFIG_DIR` / `RGSX_DATA_DIR` environment variables (ROMs in `$RGSX_DATA_DIR/roms`), then the defaults above

**ES-DE integration (macOS):**
- RGSX downloads into the folder names ES-DE scans. RGSX uses Batocera/RetroBat names, so on macOS these are translated:

| RGSX | ES-DE | RGSX | ES-DE |
|---|---|---|---|
| `3ds` | `n3ds` | `lynx` | `atarilynx` |
| `amiga500` | `amiga` | `MSX2+ (Archive)` | `msx2` |
| `amigacdtv` | `cdtv` | `o2em` | `odyssey2` |
| `c20` | `vic20` | `sg1000` | `sg-1000` |
| `cplus4` | `plus4` | `wswan` | `wonderswan` |
| `cdi` | `cdimono1` | `wswanc` | `wonderswancolor` |
| `gamecube` | `gc` | `jaguar` | `atarijaguar` |

- Other systems already use the same name. BIOS files go to the `bios` folder (`~/ROMs/BIOS` on the default case-insensitive APFS volume). Systems ES-DE does not have (`advision`, `atom`, `chihiro`, `lindbergh`, `namco2x6`, `pico`, `teknoparrot`) keep the RGSX name and need a custom ES-DE system to show up.
- Windows/Linux/Batocera behavior is unchanged. A per-platform custom folder is never translated.
- Settings (`rgsx_settings.json`): `"esde_folder_mapping": false` turns the translation off; `"rom_folder_map": {"gamecube": "gc", "pico": "segapico"}` adds or overrides entries (a value equal to the key disables that default).
- Games already downloaded under an old RGSX name (for example `gamecube`) are not detected after the change. Move them to the ES-DE folder yourself; nothing is moved automatically.
- Launch RGSX from ES-DE: `ports/RGSX/RGSX_ESDE.sh` is a launcher for the ES-DE `ports` system. Symlink it so repo updates apply (adjust the first path to where you cloned RGSX), then reload ES-DE (Menu > Other settings > Reload, or restart it):
  ```
  ln -s /path/to/RGSX/ports/RGSX/RGSX_ESDE.sh ~/ROMs/ports/RGSX_ESDE.sh
  ```
  If you copy the file instead, set `RGSX_LAUNCH_DIR` at the top of the copy to the absolute path of `ports/RGSX`. Do not overwrite `RGSX.sh`, which is the Linux/Batocera script.

**Keyboard controls:** Enter = confirm, Esc = cancel, arrows = navigate, `P` = start, `F` = filter, `H` = history, `X` = clear history, Fn+Up/Down = page up/down, Backspace = delete, Space.

**Web interface:** `http://localhost:5000`, local only by default. Set `RGSX_WEB_HOST=0.0.0.0` to expose it on your network (there is no authentication). If port 5000 is taken by AirPlay Receiver, turn it off in System Settings > General > AirDrop & Handoff.

**macOS limitations:**
- Torrent sources are not supported (no embedded qBittorrent)
- PS3 Redump decryption is not supported
- Xbox ISO repack needs `extract-xiso` on your PATH
- RAR archives use `unrar` if installed, otherwise 7-Zip (`7zz`)
- Batocera-only features (boot services, custom DNS) are hidden
- All game systems are listed, since there is no EmulationStation to define the supported ones
- Windowed by default (toggle in Settings > Display mode)

### Manual Update (if automatic update failed)
Download latest release : [RGSX_update_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)

**Installed paths:**
- `/roms/ports/RGSX` (all systems)
- `/roms/windows/RGSX` (RetroBat only)

---

## 🎮 Usage

### First Launch

- Auto-downloads system images and game lists
- Auto-configures controls if your controller is recognized
- **Controls broken?** Delete `/saves/ports/rgsx/controls.json` and restart

**Retrobat / first Windows launch**

- It is recommended to launch `RGSX Retrobat.bat` manually once, outside the Retrobat interface, to verify that everything is working.
- Allow Windows firewall prompts when they appear, especially for qBittorrent on first launch.
- Retrobat hides some system windows by default, so a first manual launch helps avoid missing an important prompt.
- The launcher then configures a local rule for the embedded qBittorrent binary and for the TCP `18572` WebUI.

**Keyboard Mode**: When no controller is detected, controls display as `[Key]` instead of icons.

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
- Screen Mode (Windows only)
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
- Web Service (Batocera/Knulli) (start web UI at boot)
- Custom DNS (Batocera/Knulli) (workaround for ISP/domain blocking)
- API Keys Status (check provider key presence)
- Connection Status (test required updates/sources sites)

---

## ✨ Features

- 🎯 **Smart System Detection** – Auto-discovers supported systems from `es_systems.cfg`
- 📦 **Intelligent Archive Handling** – Auto-extracts archives when systems don't support ZIP files
- 🔑 **Premium Unlocking** – 1Fichier API + AllDebrid/Debrid-Link/Real-Debrid/TorBox fallback for unlimited downloads
- 🎨 **Fully Customizable** – Layout (3×3 to 4×4), fonts, font sizes (UI + footer), languages (EN/FR/DE/ES/IT/PT)
- 🎮 **Controller-First Design** – Auto-mapping for popular controllers + custom remapping support
- 🔍 **Advanced Filtering** – Search by name, hide/show unsupported systems, filter platforms
- 📊 **Download Management** – Queue system, history tracking, progress notifications
- ♿ **Accessibility** – Separate font scaling for UI and footer, keyboard-only mode support

> ### 🔑 API Keys Setup
> For unlimited 1Fichier downloads, add your API key(s) to `/saves/ports/rgsx/`:
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

## Embedded qBittorrent torrent backend

Torrent downloads now run through an embedded qBittorrent binary on both Windows and Linux/Batocera.

- LAN debug WebUI: `http://YOUR_DEVICE_IP:18572`
- Default credentials: `admin` / `RGSXqbt`
- The RGSX web interface now includes a `qBittorrent` button that opens this WebUI directly.

Useful notes:
- This WebUI is intended for debugging and advanced torrent monitoring from a phone or another PC on the same local network.
- If LAN access to the WebUI does not work, first check the local Windows firewall.
- Do not expose port `18572` directly to the Internet: it is the WebUI admin port, not the BitTorrent performance port.
- If torrent connectivity is poor, prefer UPnP or forwarding the actual BitTorrent listening port configured inside qBittorrent.

## 🌐 Web Interface (Batocera/Knulli Only)

RGSX includes a web interface that launched automatically when using RGSX for remote browsing and downloading games from any device on your network.

### Accessing the Web Interface

1. **Find your Batocera IP address**:
   - Check Batocera menu: `Network Settings`
   - Or from terminal: `ip addr show`

2. **Open in browser**: `http://[BATOCERA_IP]:5000` or `http://BATOCERA:5000`
   - Example: `http://192.168.1.100:5000`

3. **Available from any device**: Phone, tablet, PC on the same network

### Web Interface Features

- 📱 **Mobile-Friendly** – Responsive design works on all screen sizes
- 🔍 **Browse All Systems** – View all platforms and games
- ⬇️ **Remote Downloads** – Queue downloads directly to your Batocera
- 📊 **Real-Time Status** – See active downloads and history
- 🎮 **Same Game Lists** – Uses identical sources as the main app


### Enable/Disable Web Service at Boot, without the need to launch RGSX

**From RGSX Menu**
1. Open **Pause Menu** (Start/ALTGr)
2. Navigate to **Settings > Web Service**
3. Toggle **Enable at Boot**
4. Restart your device


**Port Configuration**: The web service runs on port `5000` by default. Ensure this port is not blocked by firewall rules.

---

## 📁 File Structure

```
/roms/
├── ports/
│   ├── RGSX/
│   │   ├── __main__.py                # Entry point
│   │   ├── controls.py                # Input handling
│   │   ├── display.py                 # Rendering engine
│   │   ├── network.py                 # Download manager
│   │   ├── rgsx_settings.py           # Settings manager
│   │   ├── assets/controls/           # Controller profiles
│   │   ├── languages/                 # Translations (EN/FR/DE/ES/IT/PT)
│   │   └── logs/RGSX.log              # Runtime logs
│   ├── gamelist.xml
│   ├── images/
│   └── videos/
└── windows/
    ├── RGSX Retrobat.bat              # Launcher for Windows only (can be used without retrobat too)
    ├── gamelist.xml
    ├── images/
    └── videos/

/saves/ports/rgsx/
├── rgsx_settings.json        # User preferences
├── controls.json             # Control mapping
├── history.json              # Download history
├── systems_list.json         # Detected systems
├── global_search_index.json  # Global search index cache
├── platform_games_count_cache.json
├── torrent_manifest_cache.json
├── games/                    # Game databases (per platform)
├── images/                   # Platform images
├── 1FichierAPI.txt           # 1Fichier API key
├── AllDebridAPI.txt          # AllDebrid API key
├── DebridLinkAPI.txt         # Debrid-Link API key
├── RealDebridAPI.txt         # Real-Debrid API key
└── TorBoxAPI.txt              # TorBox API key
```

**macOS** (instead of the `/roms` and `/saves` layout above):
```
~/Library/Application Support/RGSX/   # settings, controls, history, logs/, games/, images/
~/ROMs/ or ~/Documents/RGSX/roms/     # ROMs (~/ROMs is used when it exists)
```

---

## 🛠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| Controls not working | Delete `/saves/ports/rgsx/controls.json` + restart app, you can try delete /roms/ports/RGSX/assets/controls/xx.json too |
| No games ? | Pause Menu > Games > Update Game Cache, then check Pause Menu > Games > Filter Platforms and Show Unsupported Platforms. Check in rgsx_settings.json in `/saves/ports/rgsx/` if the value of `sources :  mode` is  `rgsx` and not `custom` |
| Missing systems on the list? | RGSX read es_systems.cfg to show only supported systems, if you want all systems : Pause Menu > Games > Show unsupported systems |
| App crashes | Check `/roms/ports/RGSX/logs/RGSX.log` or `/roms/windows/logs/Retrobat_RGSX_log.txt` |
| Layout change not applied | Restart RGSX after changing layout |
| 7zz not found (macOS) | `brew install sevenzip` |
| Where are the logs on macOS? | `~/Library/Application Support/RGSX/logs/RGSX.log` |
| Problem downloading some Games ? | Open Pause Menu > Settings > Connection Status. If one or more required sites are red, enable Custom DNS in Settings and reboot. Also check ISP/router protections (especially ASUS web threat blocking). |

**Need help?** Share logs from `/roms/ports/RGSX/logs/` on [Discord](https://discord.gg/XPK8YG8XYC).

---

## 🤝 Contributing

- **Bug Reports**: Open GitHub issue with logs or post on Discord
- **Feature Requests**: Discuss on Discord first, then open issue
- **Code Contributions**: 
  ```bash
  git checkout -b feature/your-feature
  # Test on Batocera/RetroBat
  # Submit Pull Request
  ```

---

## 📝 License

Free and open-source software. Use, modify, and distribute freely.

## Thanks to all contributors, and followers of this app

**If you want to support my project you can buy me a beer :  https://bit.ly/donate-to-rgsx**
<a href="https://github.com/RetroGameSets/RGSX/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=RetroGameSets/RGSX" />
</a>
[![Stargazers over time](https://starchart.cc/RetroGameSets/RGSX.svg?variant=adaptive)](https://starchart.cc/RetroGameSets/RGSX)

**Developed with ❤️ for the retro gaming community.**
