#!/usr/bin/env python3
"""Unit tests for compositor window parsing and PID-based filtering.

Covers sway, hyprland, and niri backends.
"""
from __future__ import annotations

import json
import os
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
fftabs = SourceFileLoader("fftabs", str(REPO_ROOT / "fftabs")).load_module()


class TestCompositorWindowParsing(unittest.TestCase):
    def test_sway_windows_parsing(self):
        sway_tree = {
            "id": 1,
            "type": "root",
            "nodes": [
                {
                    "id": 2,
                    "type": "output",
                    "nodes": [
                        {
                            "id": 3,
                            "type": "con",
                            "app_id": "firefox",
                            "name": "Mozilla Firefox - Work",
                            "pid": 1111,
                            "nodes": [],
                            "floating_nodes": [],
                        },
                        {
                            "id": 4,
                            "type": "con",
                            "window_properties": {"class": "firefox"},
                            "name": "Mozilla Firefox - Personal",
                            "pid": 2222,
                            "nodes": [],
                            "floating_nodes": [],
                        },
                        {
                            "id": 5,
                            "type": "con",
                            "app_id": "alacritty",
                            "name": "Terminal",
                            "pid": 3333,
                            "nodes": [],
                            "floating_nodes": [],
                        },
                    ],
                    "floating_nodes": [],
                }
            ],
            "floating_nodes": [],
        }

        with patch.object(fftabs, "_run", return_value=json.dumps(sway_tree)):
            wins = fftabs._sway_windows()
            self.assertEqual(len(wins), 3)
            self.assertEqual(wins[0]["id"], 3)
            self.assertEqual(wins[0]["title"], "Mozilla Firefox - Work")
            self.assertEqual(wins[0]["app"], "firefox")
            self.assertEqual(wins[0]["pid"], 1111)

            self.assertEqual(wins[1]["id"], 4)
            self.assertEqual(wins[1]["pid"], 2222)

    def test_hypr_windows_parsing(self):
        hypr_clients = [
            {
                "address": "0x1234",
                "title": "Firefox Tab 1",
                "class": "firefox",
                "pid": 4444,
            },
            {
                "address": "0x5678",
                "title": "Firefox Tab 2",
                "class": "firefox",
                "pid": 5555,
            },
        ]

        with patch.object(fftabs, "_run", return_value=json.dumps(hypr_clients)):
            wins = fftabs._hypr_windows()
            self.assertEqual(len(wins), 2)
            self.assertEqual(wins[0]["id"], "0x1234")
            self.assertEqual(wins[0]["title"], "Firefox Tab 1")
            self.assertEqual(wins[0]["app"], "firefox")
            self.assertEqual(wins[0]["pid"], 4444)

    def test_niri_windows_parsing(self):
        niri_windows = [
            {"id": 10, "title": "GitHub - profile A", "app_id": "firefox", "pid": 7777},
            {"id": 20, "title": "GitHub - profile B", "app_id": "firefox", "pid": 8888},
            {"id": 30, "title": "Editor", "app_id": "code", "pid": 9999},
        ]

        with patch.object(fftabs, "_run", return_value=json.dumps(niri_windows)):
            wins = fftabs._niri_windows()
            self.assertEqual(len(wins), 3)
            self.assertEqual(wins[0]["id"], 10)
            self.assertEqual(wins[0]["title"], "GitHub - profile A")
            self.assertEqual(wins[0]["app"], "firefox")
            self.assertEqual(wins[0]["pid"], 7777)


class TestCompositorFocusFiltering(unittest.TestCase):
    def setUp(self):
        self.ran_cmds = []

        def mock_run(cmd):
            self.ran_cmds.append(cmd)
            return "ok"

        self.mock_run = mock_run

    def test_niri_same_title_in_two_profiles_pid_match(self):
        # Two windows across two profiles have identical titles "Google"
        windows = [
            {"id": 101, "title": "Google — Mozilla Firefox", "app": "firefox", "pid": 1000},
            {"id": 202, "title": "Google — Mozilla Firefox", "app": "firefox", "pid": 2000},
        ]

        with patch.dict(os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}), \
             patch.dict(fftabs.BACKENDS, {"niri": (lambda: windows, lambda i: ["niri", "msg", "action", "focus-window", "--id", str(i)])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            # Switch tab belonging to PID 2000
            fftabs.focus_firefox_window("Google", firefox_pid=2000)
            self.assertEqual(self.ran_cmds, [["niri", "msg", "action", "focus-window", "--id", "202"]])

            self.ran_cmds.clear()
            # Switch tab belonging to PID 1000
            fftabs.focus_firefox_window("Google", firefox_pid=1000)
            self.assertEqual(self.ran_cmds, [["niri", "msg", "action", "focus-window", "--id", "101"]])

    def test_pid_missing_fallback_to_title(self):
        # Compositor reported pid as None or missing
        windows = [
            {"id": 101, "title": "Alpha — Mozilla Firefox", "app": "firefox", "pid": None},
            {"id": 202, "title": "Beta — Mozilla Firefox", "app": "firefox", "pid": None},
        ]

        with patch.dict(os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}), \
             patch.dict(fftabs.BACKENDS, {"niri": (lambda: windows, lambda i: ["niri", "focus", str(i)])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            fftabs.focus_firefox_window("Beta", firefox_pid=2000)
            # PID 2000 not found in window pids, falls back to title matching -> focuses 202
            self.assertEqual(self.ran_cmds, [["niri", "focus", "202"]])

    def test_pid_not_found_fallback_to_title(self):
        windows = [
            {"id": 101, "title": "Alpha — Mozilla Firefox", "app": "firefox", "pid": 5555},
            {"id": 202, "title": "Beta — Mozilla Firefox", "app": "firefox", "pid": 6666},
        ]

        with patch.dict(os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}), \
             patch.dict(fftabs.BACKENDS, {"niri": (lambda: windows, lambda i: ["niri", "focus", str(i)])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            # PID 9999 doesn't match any window -> falls back to title matching for "Alpha"
            fftabs.focus_firefox_window("Alpha", firefox_pid=9999)
            self.assertEqual(self.ran_cmds, [["niri", "focus", "101"]])

    def test_single_window_focused_regardless_of_pid_or_title(self):
        windows = [
            {"id": 50, "title": "Any Page — Mozilla Firefox", "app": "firefox", "pid": 1234},
        ]

        with patch.dict(os.environ, {"NIRI_SOCKET": "/tmp/niri.sock"}), \
             patch.dict(fftabs.BACKENDS, {"niri": (lambda: windows, lambda i: ["niri", "focus", str(i)])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            fftabs.focus_firefox_window("Something Else", firefox_pid=None)
            self.assertEqual(self.ran_cmds, [["niri", "focus", "50"]])

    def test_sway_pid_filter(self):
        windows = [
            {"id": 11, "title": "Tab Title — Mozilla Firefox", "app": "firefox", "pid": 3001},
            {"id": 12, "title": "Tab Title — Mozilla Firefox", "app": "firefox", "pid": 3002},
        ]

        with patch.dict(os.environ, {"SWAYSOCK": "/tmp/sway.sock", "NIRI_SOCKET": ""}), \
             patch.dict(fftabs.BACKENDS, {"sway": (lambda: windows, lambda i: ["swaymsg", f"[con_id={i}] focus"])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            fftabs.focus_firefox_window("Tab Title", firefox_pid=3002)
            self.assertEqual(self.ran_cmds, [["swaymsg", "[con_id=12] focus"]])

    def test_hyprland_pid_filter(self):
        windows = [
            {"id": "0xa", "title": "Tab Title — Mozilla Firefox", "app": "firefox", "pid": 4001},
            {"id": "0xb", "title": "Tab Title — Mozilla Firefox", "app": "firefox", "pid": 4002},
        ]

        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "sig", "SWAYSOCK": "", "NIRI_SOCKET": ""}), \
             patch.dict(fftabs.BACKENDS, {"hyprland": (lambda: windows, lambda i: ["hyprctl", "dispatch", "focuswindow", f"address:{i}"])}), \
             patch.object(fftabs, "_run", side_effect=self.mock_run):

            fftabs.focus_firefox_window("Tab Title", firefox_pid=4001)
            self.assertEqual(self.ran_cmds, [["hyprctl", "dispatch", "focuswindow", "address:0xa"]])


if __name__ == "__main__":
    unittest.main()
