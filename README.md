# fftabs 🦊

> **Ultra-fast, multi-profile Firefox tab switcher and manager for Linux desktop environments and window managers.**

Switch, search, and close tabs across multiple Firefox windows and profiles from **Rofi**, **dmenu**, or the shell — with high-resolution favicons, multi-profile awareness, deterministic compositor window focusing, and **zero background daemons**. Built entirely with the **Python 3 standard library**.

---

## 📑 Table of Contents

- [Overview & Architecture](#-overview--architecture)
- [Key Features](#-key-features)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
  - [1. Install CLI & Native Messaging Host](#1-install-cli--native-messaging-host)
  - [2. Install the Firefox Extension](#2-install-the-firefox-extension)
  - [3. Verify the Setup](#3-verify-the-setup)
- [Usage Guide](#-usage-guide)
  - [Interactive Rofi Switcher](#interactive-rofi-switcher)
  - [Command-Line Scripting & JSON](#command-line-scripting--json)
  - [Custom Themes (VS Code Palette included)](#custom-themes)
- [Window Manager Keybindings](#-window-manager-keybindings)
- [How It Works Under the Hood](#-how-it-works-under-the-hood)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🔍 Overview & Architecture

Firefox does not provide an external IPC or D-Bus API for external applications to query or switch tabs. `fftabs` solves this cleanly using Firefox's sanctioned **Native Messaging** protocol:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Firefox Browser (Profile A, Profile B, ...)                           │
│  └── extension/ (Tabs API)                                             │
│        │  Native Messaging (32-bit length-prefixed JSON via stdio)     │
│        ▼                                                               │
│  fftabs host (Spawned automatically by Firefox)                        │
│        │  Exposes per-user Unix Domain Socket (mode 0600)              │
│        ▼  $XDG_RUNTIME_DIR/fftabs-<firefox_pid>.sock                   │
└────────┬───────────────────────────────────────────────────────────────┘
         │
         │  JSON-RPC over Unix Socket
         ▼
┌────────────────────────────────────────────────────────────────────────┐
│  fftabs CLI / Rofi Front-end                                           │
│  ├── Query & aggregate tabs across all active profiles                 │
│  ├── Display interactive picker with cached favicons & metadata        │
│  ├── Activate selected tab via extension RPC                           │
│  └── Deterministically focus compositor window (Niri / Sway / Hyprland)│
└────────────────────────────────────────────────────────────────────────┘
```

Everything runs strictly on your local machine. No external services, no analytics, no persistent memory footprint when not in use.

---

## ✨ Key Features

- ⚡ **Zero Dependencies / Pure Python Standard Library**: No pip packages required to run the core CLI, native messaging host, or tab switcher.
- 👥 **Multi-Profile Native**: Automatically discovers profile names by querying Firefox's internal Profile Groups SQLite database and active file descriptors. Prefix tags like `work/win 1` make navigation seamless.
- 🎯 **Deterministic Compositor Focusing**: Eliminates window-switching ambiguity by filtering windows by `firefox_pid` before matching titles. First-class support for **Niri**, **Sway**, **Hyprland**, and **X11**.
- 🖼️ **Favicons & Rich Metadata**: Downloads and caches tab favicons to display alongside tab titles. Shows container names (Work, Personal, etc.), audio playback state, mute status, pinned state, and unloaded/discarded status.
- ⌨️ **Interactive Controls**: In Rofi, press **Enter** to switch to a tab, or press **Alt+d** to close the highlighted tab in-place without dismissing the menu.
- 🔁 **Alt-Tab Behavior**: Supports `--previous` to immediately preselect the last active tab, giving you an instantaneous keyboard-driven tab switcher.
- 🛠️ **Fully Scriptable**: Outputs tab lists in tab-separated values (TSV) or raw JSON for integration into custom shell scripts, Waybar modules, or polybar widgets.

---

## 📦 Prerequisites

- **Python 3.8+**
- **Firefox** (Standard Release, Developer Edition, Nightly, or ESR)
- **Rofi** or **rofi-wayland** (optional, required for the GUI picker)
- **python-pillow** (optional, recommended for converting ICO/WEBP favicons to PNG for Rofi)

On Arch Linux:
```bash
sudo pacman -S python rofi-wayland python-pillow
```

---

## 🚀 Installation

### 1. Install CLI & Native Messaging Host

Clone this repository and register the native messaging host:

```bash
git clone https://github.com/krishnadev7777/firefox_tab_switcher.git
cd firefox_tab_switcher

# Register host wrapper in ~/.local/share/fftabs/ and manifest in ~/.mozilla/native-messaging-hosts/
./fftabs install

# Symlink fftabs into your user PATH
mkdir -p ~/.local/bin
ln -sf "$PWD/fftabs" ~/.local/bin/fftabs
```

### 2. Install the Firefox Extension

Choose the method matching your Firefox setup:

#### Option A: Install from Signed XPI (Standard Firefox Release)
If you have generated or downloaded a signed `.xpi` (via Mozilla AMO):
1. Open Firefox and drag-and-drop the `.xpi` file into any Firefox window (or press `Ctrl+O` and select the file).
2. Click **Add** when prompted.
3. Open `about:addons` → click **fftabs** → check **"Allow in Private Windows"** if you want private browsing tabs to appear in the switcher.

#### Option B: Self-Signing with web-ext (For Personal Use on Stock Firefox)
Mozilla allows instantaneous automated signing for personal unlisted extensions:
```bash
npx web-ext sign \
  --source-dir extension \
  --channel=unlisted \
  --api-key="YOUR_AMO_JWT_ISSUER" \
  --api-secret="YOUR_AMO_JWT_SECRET"
```
The signed `.xpi` will be output to `./web-ext-artifacts/`. Install it via `about:addons` → ⚙ → *Install Add-on From File...*.

#### Option C: Temporary Loading (Quick Testing)
1. Open `about:debugging#/runtime/this-firefox` in Firefox.
2. Click **Load Temporary Add-on...**.
3. Select `extension/manifest.json`.
*(Note: Temporary add-ons are cleared when Firefox completely exits).*

### 3. Verify the Setup

Run `fftabs status` to verify the entire connection pipeline:

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

## 💡 Usage Guide

### Interactive Rofi Switcher

```bash
# Launch interactive tab picker (most recently used order)
fftabs

# Preselect the previously active tab (ideal for binding to Alt+Tab or Super+Tab)
fftabs rofi --previous

# Order tabs by window and position rather than recent usage
fftabs rofi --sort window

# Filter tabs to a specific profile
fftabs rofi --profile work

# Pass arbitrary flags directly to rofi (after --)
fftabs rofi -- -theme ~/.config/rofi/my-theme.rasi
```

#### Keyboard Shortcuts in Rofi:
- **`Enter`**: Switch to the highlighted tab and focus its containing window.
- **`Alt+d`**: Close the highlighted tab in the background and keep the picker open on the next row.
- **`Esc`**: Dismiss the switcher.

---

### Command-Line Scripting & JSON

`fftabs` is designed to be easily integrated into shell scripts, automation pipelines, and status bars:

```bash
# List all tabs (tab-separated: ref, profile, window, current, title, url)
fftabs list

# Output full tab structure as JSON
fftabs list --json

# Filter tabs using jq
fftabs list --json | jq '.[] | select(.audible == true) | {title, profile: ._profile_name}'

# Programmatically switch to a tab by ref (e.g. bare ID, or profile:ID)
fftabs switch 42
fftabs switch work:42

# Programmatically close a tab
fftabs close work:42
```

---

### Custom Themes

A VS Code Command Palette-style Rofi theme (`vscode.rasi`) is included in the root of the repository:

```bash
fftabs rofi -- -theme ./vscode.rasi
```

---

## ⌨️ Window Manager Keybindings

Bind `fftabs` to a keyboard shortcut for instant access:

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

## ⚙️ How It Works Under the Hood

### 1. WebExtension & Native Messaging Bridge
When Firefox starts with the extension enabled, it connects to the native messaging host defined in `~/.mozilla/native-messaging-hosts/fftabs.json`. Firefox launches `./fftabs host` as a child process and communicates via standard input/output using 32-bit length-prefixed JSON payloads.

### 2. IPC Sockets
The `fftabs host` creates a Unix domain socket at `$XDG_RUNTIME_DIR/fftabs-<firefox_pid>.sock` with file mode `0600` (readable/writable only by your Linux user account). When you invoke the `fftabs` CLI, it queries all active sockets concurrently with a 5-second timeout, aggregating tabs across all running Firefox profiles.

### 3. Profile Discovery
Rather than requiring the user to manually configure profile names or modify extension code, `fftabs` automatically inspects `/proc/<firefox_pid>/fd` to discover the active profile directory lock (`.parentlock`), then queries Firefox's `Profile Groups/*.sqlite` database or `profiles.ini` to resolve human-readable profile names (e.g. `work`, `personal`).

### 4. Deterministic Compositor Focusing
When you select a tab in Rofi, two actions happen:
1. The extension executes `browser.tabs.update(tabId, { active: true })` and `browser.windows.update(windowId, { focused: true })`.
2. To bring the Firefox window to the foreground in Wayland or X11, `fftabs` queries the active window manager (Niri, Sway, Hyprland, or X11 via `wmctrl`/`xdotool`). It first filters windows matching the specific Firefox instance PID, then matches the window title, avoiding misfocusing when multiple profiles have tabs with identical titles.

---

## 🔧 Troubleshooting

### `fftabs status` reports `firefox: NOT CONNECTED`
- Make sure Firefox is running.
- Ensure the extension is loaded and enabled in `about:addons`.
- Verify that `~/.mozilla/native-messaging-hosts/fftabs.json` exists and points to the correct executable wrapper. Run `./fftabs install` to regenerate it.
- Check permissions: if Firefox was installed via Flatpak or Snap, native messaging requires host portal permissions (native package installation via `pacman`, `apt`, or `dnf` is recommended).

### Tabs from Private Windows do not appear
By default, Firefox restricts extensions from accessing private browsing windows. Open `about:addons` → click **fftabs** → toggle **Run in Private Windows** to **Allow**.

### Favicons are missing in Rofi
- Ensure `show-icons: true;` is present in your Rofi configuration or theme.
- Install `python-pillow` so ICO and WEBP favicons can be dynamically converted to PNG format for Rofi's icon fetcher.

---

## 🤝 Contributing

Contributions, bug reports, and suggestions are very welcome!

### Development Setup
1. Fork and clone the repository.
2. The codebase has **no external build steps** or third-party runtime dependencies:
   ```bash
   git clone https://github.com/krishnadev7777/firefox_tab_switcher.git
   cd firefox_tab_switcher
   ```
3. Run the automated test suite:
   ```bash
   python3 -m unittest discover tests/ -v
   ```

### Guidelines
- **Standard Library Only**: The CLI and host logic must remain runnable with the Python 3 standard library.
- **Test Coverage**: When adding compositor backends, profile detection logic, or CLI flags, add corresponding unit tests in `tests/`.
- **Formatting**: Keep Python code clean, typed with type annotations, and formatted.

---

## 📄 License

This project is open-source software licensed under the [MIT License](file:///home/laperex/Programming/firefox_tab_switcher/LICENSE).
