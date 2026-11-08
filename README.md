# fftabs

Multi-profile Firefox tab switcher and manager for Linux desktop environments and window managers.

Switch, search, and close tabs across multiple Firefox windows and profiles from **Rofi**, **dmenu**, or the shell — featuring cached favicon support, multi-profile awareness, deterministic compositor window focusing, and no background daemons. Implemented entirely with the **Python 3 standard library**.

---

## Table of Contents

- [Overview and Architecture](#overview-and-architecture)
- [Key Features](#key-features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [1. Install CLI and Native Messaging Host](#1-install-cli-and-native-messaging-host)
  - [2. Install the Firefox Extension](#2-install-the-firefox-extension)
  - [3. Verify the Pipeline](#3-verify-the-pipeline)
- [Usage Guide](#usage-guide)
  - [Interactive Rofi Switcher](#interactive-rofi-switcher)
  - [Command-Line Scripting and JSON](#command-line-scripting-and-json)
  - [Custom Themes](#custom-themes)
- [Auto-Updates for Self-Hosted Extensions](#auto-updates-for-self-hosted-extensions)
- [Window Manager Keybindings](#window-manager-keybindings)
- [Technical Architecture](#technical-architecture)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Overview and Architecture

Firefox does not provide an external IPC or D-Bus interface for external processes to query or switch tabs. `fftabs` resolves this using Firefox's standard **Native Messaging** protocol:

```
+------------------------------------------------------------------------+
|  Firefox Browser (Profile A, Profile B, ...)                           |
|  └── extension/ (Tabs API)                                             |
|        │  Native Messaging (32-bit length-prefixed JSON via stdio)     |
|        ▼                                                               |
|  fftabs host (Spawned automatically by Firefox)                        |
|        │  Exposes per-user Unix Domain Socket (mode 0600)              |
|        ▼  $XDG_RUNTIME_DIR/fftabs-<firefox_pid>.sock                   |
+--------┬---------------------------------------------------------------+
         │
         │  JSON-RPC over Unix Socket
         ▼
+------------------------------------------------------------------------+
|  fftabs CLI / Rofi Front-end                                           |
|  ├── Query & aggregate tabs across all active profiles                 |
|  ├── Display interactive picker with cached favicons & metadata        |
|  ├── Activate selected tab via extension RPC                           |
|  └── Deterministically focus compositor window (Niri / Sway / Hyprland)|
+------------------------------------------------------------------------+
```

All IPC operations take place locally through Unix domain sockets. No network services, background polling loops, or third-party dependencies are required.

---

## Key Features

- **Pure Python Standard Library**: Core CLI, native messaging host, and tab management require only Python 3.8+ with no external packages.
- **Multi-Profile Native**: Automatically discovers profile names by inspecting Firefox's active file descriptors and internal Profile Groups SQLite database (`Profile Groups/*.sqlite`). Profile tags (e.g. `work/win 1`) allow clear visual disambiguation.
- **Deterministic Window Focusing**: Resolves window activation on Wayland (**Niri**, **Sway**, **Hyprland**) and **X11** by matching the Firefox process PID before matching window titles, preventing focus collisions when different profiles have tabs with identical titles.
- **Favicons and Tab Metadata**: Downloads and caches tab favicons to display alongside tab titles. Shows container names (Work, Personal, etc.), audio state, mute status, pinned state, and unloaded/discarded state.
- **In-Place Tab Actions**: Press **Enter** to switch to a tab, or **Alt+d** to close the selected tab directly in the picker without dismissing the menu.
- **Alt-Tab Switching Workflow**: Supports `--previous` to preselect the most recently used tab, enabling seamless keyboard-driven back-and-forth tab switching.
- **Scriptable Interface**: Supports tab-separated values (TSV) and structured JSON outputs for integration into status bars (Waybar, Polybar), shell scripts, and external tools.

---

## Prerequisites

- **Python 3.8+**
- **Firefox** (Standard Release, Developer Edition, Nightly, or ESR)
- **Rofi** or **rofi-wayland** (optional, required for the interactive graphical picker)
- **python-pillow** (optional, recommended for converting ICO/WEBP favicons to PNG for Rofi)

On Arch Linux:
```bash
sudo pacman -S python rofi-wayland python-pillow
```

---

## Installation

### 1. Install CLI and Native Messaging Host

Clone the repository and register the native messaging host:

```bash
git clone https://github.com/laperex/fftabs.git
cd fftabs

# Registers host wrapper in ~/.local/share/fftabs/ and manifest in ~/.mozilla/native-messaging-hosts/
./fftabs install

# Symlink fftabs into your user PATH
mkdir -p ~/.local/bin
ln -sf "$PWD/fftabs" ~/.local/bin/fftabs
```

### 2. Install the Firefox Extension

Choose the method that matches your environment:

#### Option A: Install from a Signed XPI (Standard Firefox Release)
If you have generated or downloaded a signed `.xpi`:
1. Open Firefox and drag-and-drop the `.xpi` file into any Firefox window (or open it with `firefox <path-to-.xpi>`).
2. Click **Add** when prompted.
3. Open `about:addons` -> click **fftabs** -> check **"Allow in Private Windows"** if you want private browsing tabs to appear in the switcher.

#### Option B: Self-Signing with web-ext (For Personal Use on Stock Firefox)
Mozilla allows automated signing for personal unlisted extensions:
```bash
npx web-ext sign \
  --source-dir extension \
  --channel=unlisted \
  --api-key="YOUR_AMO_JWT_ISSUER" \
  --api-secret="YOUR_AMO_JWT_SECRET"
```
The signed `.xpi` will be written to `./web-ext-artifacts/`. Install it in Firefox via `about:addons` -> gear icon -> *Install Add-on From File...*.

#### Option C: Temporary Loading (Quick Testing)
1. Navigate to `about:debugging#/runtime/this-firefox` in Firefox.
2. Click **Load Temporary Add-on...**.
3. Select `extension/manifest.json`.

*(Note: Temporary add-ons are unloaded when Firefox exits).*

### 3. Verify the Pipeline

Run `fftabs status` to verify end-to-end communication:

```bash
fftabs status
```

Expected output:
```text
native manifest : ok  (/home/user/.mozilla/native-messaging-hosts/fftabs.json)
host wrapper    : ok  (/home/user/.local/share/fftabs/fftabs-host)
rofi            : /usr/bin/rofi
Pillow          : yes (ICO/WEBP favicons are converted to PNG)
compositor      : niri
firefox         : host pid 464673  ok  profile=work
firefox         : host pid 711732  ok  profile=personal
```

---

## Usage Guide

### Interactive Rofi Switcher

```bash
# Launch interactive tab picker (most recently viewed window first, MRU tabs inside)
fftabs

# Preselect the previously active tab (ideal for Alt+Tab shortcuts)
fftabs rofi --previous

# Sort options:
# - window-recent (default): tabs of the most recently viewed window first; MRU inside
fftabs rofi --sort window-recent

# - recent: global flat MRU order across all windows and profiles
fftabs rofi --sort recent

# - window-index: most recently viewed window first; tabs in tab-bar order (index)
fftabs rofi --sort window-index

# - window-num: legacy static window number order (win 1, win 2...)
fftabs rofi --sort window-num

# Filter tabs to a specific profile
fftabs rofi --profile work

# Pass arbitrary flags directly to rofi (after --)
fftabs rofi -- -theme ~/.config/rofi/my-theme.rasi
```

#### Keyboard Shortcuts in Rofi:
- **`Enter`**: Switch to the highlighted tab and focus its containing window.
- **`Alt+d`**: Close the highlighted tab in the background without dismissing the picker.
- **`Alt+o`**: Close all other tabs in the same window (with preview confirmation).
- **`Alt+r`**: Close tabs to the right of the highlighted tab on the window's tab bar.
- **`Alt+l`**: Close tabs to the left of the highlighted tab on the window's tab bar.
- **`Alt+n`**: Open the new tab prompt with history autocomplete and DuckDuckGo search.
- **`Esc`**: Dismiss the switcher.

---

### Opening New Tabs & Autocomplete

`fftabs` allows opening URLs or search queries in the currently focused (or MRU) Firefox window:

```bash
# Interactive new tab prompt with browsing history autocomplete
fftabs open
fftabs new

# Open a URL directly in the focused window
fftabs open github.com
fftabs open https://docs.rs/tokio

# Search with DuckDuckGo in a new tab
fftabs open "arch linux wayland"

# Target a specific profile
fftabs open --profile work https://intranet.company.com
```

---

### Scoped Tab Closing

In addition to closing individual tabs, `fftabs` supports closing groups of tabs in a window:

```bash
# Close all other tabs in the same window (preserves pinned tabs)
fftabs close-others work:42
fftabs close work:42 --others

# Close tabs to the right of the target tab on the tab bar
fftabs close-right 42
fftabs close 42 --right

# Close tabs to the left of the target tab on the tab bar
fftabs close-left 42
fftabs close 42 --left

# Skip interactive confirmation with -y
fftabs close-right 42 -y

# Also close pinned tabs
fftabs close-others 42 --close-pinned
```

---

### Command-Line Scripting and JSON

`fftabs` provides machine-readable outputs for shell scripts and status bars:

```bash
# List all tabs (tab-separated: ref, profile, window, current, title, url)
fftabs list

# Output full tab structure as JSON
fftabs list --json

# Filter tabs using jq (e.g. audible tabs)
fftabs list --json | jq '.[] | select(.audible == true) | {title, profile: ._profile_name}'

# Programmatically switch to a tab by ref (bare ID, or profile:ID)
fftabs switch 42
fftabs switch work:42

# Programmatically close a tab
fftabs close work:42
```

---

### Custom Themes

You can customize Rofi's appearance by passing any standard Rofi `.rasi` theme:

```bash
fftabs rofi -- -theme ~/.config/rofi/my-theme.rasi
```

---

## Auto-Updates for Self-Hosted Extensions

If you distribute or self-host your signed extension outside the public addons.mozilla.org directory, you can configure automatic updates so Firefox checks for and installs new releases automatically.

### 1. Configure `update_url` in `manifest.json`

In `extension/manifest.json`, add the `update_url` property pointing to a hosted `updates.json` manifest:

```json
{
  "manifest_version": 2,
  "name": "fftabs",
  "version": "0.1.3",
  "browser_specific_settings": {
    "gecko": {
      "id": "fftabs@laperex",
      "strict_min_version": "140.0",
      "update_url": "https://raw.githubusercontent.com/laperex/fftabs/main/updates.json"
    }
  }
}
```

### 2. Create the `updates.json` Manifest

Place an `updates.json` file in your repository root or hosting server using Mozilla's update manifest schema:

```json
{
  "addons": {
    "fftabs@laperex": {
      "updates": [
        {
          "version": "0.1.3",
          "update_link": "https://github.com/laperex/fftabs/releases/download/v0.1.3/fftabs-0.1.3.xpi"
        }
      ]
    }
  }
}
```

### 3. How Auto-Update Verification Works
- Firefox periodically fetches `update_url` over HTTPS.
- When `version` in `updates.json` is greater than the installed version, Firefox downloads the `.xpi` from `update_link`.
- Firefox verifies that the downloaded `.xpi` is signed by Mozilla with the same extension ID (`id`), then installs the update in the background.

*(Note: If you publish your extension publicly on addons.mozilla.org, AMO handles updates automatically and `update_url` is not required).*

---

## Window Manager Keybindings

### Niri (`~/.config/niri/config.kdl`)
```kdl
binds {
    Mod+Tab { spawn "fftabs" "rofi" "--previous"; }
    Mod+Shift+Tab { spawn "fftabs" "rofi"; }
}
```

### Sway (`~/.config/sway/config`)
```i3config
bindsym $mod+Tab exec fftabs rofi --previous
bindsym $mod+Shift+Tab exec fftabs rofi
```

### Hyprland (`~/.config/hypr/hyprland.conf`)
```ini
bind = $mainMod, Tab, exec, fftabs rofi --previous
bind = $mainMod SHIFT, Tab, exec, fftabs rofi
```

---

## Technical Architecture

### 1. WebExtension and Native Messaging Bridge
When Firefox launches with the extension installed, it connects to the native messaging host configured at `~/.mozilla/native-messaging-hosts/fftabs.json`. Firefox starts `./fftabs host` as a subprocess and communicates via standard I/O using 32-bit length-prefixed JSON messages.

### 2. IPC Sockets
The `fftabs host` establishes a Unix domain socket at `$XDG_RUNTIME_DIR/fftabs-<firefox_pid>.sock` with file mode `0600` (restricted to the current Linux user). When the `fftabs` CLI is invoked, it queries all active sockets concurrently with a 5-second timeout, aggregating tabs across all active Firefox profiles.

### 3. Profile Discovery
Rather than requiring manual profile configuration, `fftabs` inspects `/proc/<firefox_pid>/fd` to find the active profile directory lock (`.parentlock`), then queries Firefox's `Profile Groups/*.sqlite` database or `profiles.ini` to resolve human-readable profile names (such as `work` or `personal`).

### 4. Deterministic Window Focusing
Selecting a tab in Rofi executes two steps:
1. The extension issues `browser.tabs.update(tabId, { active: true })` and `browser.windows.update(windowId, { focused: true })`.
2. To bring the window to the foreground on Wayland or X11, `fftabs` queries the active window manager (Niri, Sway, Hyprland, or X11 via `wmctrl`/`xdotool`). It filters windows matching the target Firefox instance PID before matching the window title, avoiding misfocusing when multiple profiles have tabs with identical titles.

---

## Troubleshooting

### `fftabs status` reports `firefox: NOT CONNECTED`
- Verify that Firefox is running.
- Ensure the extension is enabled in `about:addons`.
- Verify that `~/.mozilla/native-messaging-hosts/fftabs.json` exists and points to the correct wrapper. Run `./fftabs install` to regenerate it.
- Package isolation: If Firefox is running inside a Flatpak or Snap sandbox, native messaging requires host portal access. A native distribution package (Arch, Debian, Fedora) is recommended.

### Tabs from Private Windows do not appear
Firefox restricts extensions from private windows by default. Open `about:addons` -> click **fftabs** -> toggle **Run in Private Windows** to **Allow**.

### Favicons are missing in Rofi
- Ensure `show-icons: true;` is enabled in your Rofi configuration or theme.
- Install `python-pillow` so that ICO and WEBP favicons can be converted to PNG for Rofi's icon cache.

---

## Contributing

Contributions, bug reports, and pull requests are welcome.

### Development Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/laperex/fftabs.git
   cd fftabs
   ```
2. Run the test suite:
   ```bash
   python3 -m unittest discover tests/ -v
   ```

### Contribution Guidelines
- **Standard Library Only**: The CLI and host logic must remain dependency-free using the Python 3 standard library.
- **Test Coverage**: When adding profile discovery logic, compositor backends, or CLI options, include corresponding unit tests in `tests/`.
- **Code Style**: Keep Python code cleanly typed, structured, and formatted.

---

## License

This project is licensed under the [MIT License](LICENSE).
