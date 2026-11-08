#!/usr/bin/env python3
"""Integration and unit tests for multi-profile support in fftabs."""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
fftabs = SourceFileLoader("fftabs", str(REPO_ROOT / "fftabs")).load_module()
from tests.fake_firefox import FakeFirefoxController, setup_temp_profile


class TestProfileDetectionUnit(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(fftabs.slugify("Original profile"), "original-profile")
        self.assertEqual(fftabs.slugify("thereaper7854"), "thereaper7854")
        self.assertEqual(fftabs.slugify("My Profile @ 2026!"), "my-profile-2026")
        self.assertEqual(fftabs.slugify("---test---"), "test")
        self.assertEqual(fftabs.slugify(""), "unknown")

    def test_detect_from_groups_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup_temp_profile(root, "Work Profile", "prof1.Work", db_mode="groups_db")
            name = fftabs._query_profile_groups_db(root, "prof1.Work")
            self.assertEqual(name, "Work Profile")

    def test_detect_from_ini_relative(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup_temp_profile(root, "Personal", "prof2.Personal", db_mode="ini")
            name = fftabs._parse_profiles_ini(root, "prof2.Personal")
            self.assertEqual(name, "Personal")

    def test_detect_from_ini_absolute(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prof_dir = root / "custom_dir"
            prof_dir.mkdir()
            ini_path = root / "profiles.ini"
            ini_path.write_text(
                f"[Profile0]\nName=Custom\nIsRelative=0\nPath={prof_dir}\n"
            )
            name = fftabs._parse_profiles_ini(root, "custom_dir")
            self.assertEqual(name, "Custom")

    def test_profile_from_cmdline(self):
        with tempfile.TemporaryDirectory() as td:
            cmd_file = Path(td) / "cmdline"
            # Simulate: /usr/lib/firefox/firefox --profile /path/to/my.profile --other
            cmd_file.write_bytes(b"/usr/lib/firefox/firefox\x00--profile\x00/path/to/my.profile\x00--other\x00")
            with patch("pathlib.Path.read_bytes", return_value=cmd_file.read_bytes()):
                name = fftabs._profile_from_cmdline(12345)
                self.assertEqual(name, "my.profile")

            # Simulate: /usr/lib/firefox/firefox -P WorkProfile
            cmd_file.write_bytes(b"/usr/lib/firefox/firefox\x00-P\x00WorkProfile\x00")
            with patch("pathlib.Path.read_bytes", return_value=cmd_file.read_bytes()):
                name = fftabs._profile_from_cmdline(12345)
                self.assertEqual(name, "WorkProfile")


class TestMultiProfileIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime_dir = tempfile.mkdtemp(prefix="fftabs_test_rt_")
        cls.orig_rt = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = cls.runtime_dir

    @classmethod
    def tearDownClass(cls):
        if cls.orig_rt:
            os.environ["XDG_RUNTIME_DIR"] = cls.orig_rt
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        shutil.rmtree(cls.runtime_dir, ignore_errors=True)

    def tearDown(self):
        # Clean any stray sockets in test runtime dir
        for p in Path(self.runtime_dir).glob("fftabs-*.sock"):
            try:
                p.unlink()
            except OSError:
                pass

    def test_single_and_multi_profile_lifecycle(self):
        tabs1 = [
            {
                "id": 10,
                "index": 0,
                "window": {"id": 100, "n": 1, "focused": True, "private": False},
                "title": "Work Inbox",
                "url": "https://mail.work.com",
                "favIconUrl": "",
                "active": True,
                "pinned": False,
                "audible": False,
                "muted": False,
                "discarded": False,
                "lastAccessed": 1000,
                "container": None,
            },
            {
                "id": 11,
                "index": 1,
                "window": {"id": 100, "n": 1, "focused": False, "private": False},
                "title": "Work Docs",
                "url": "https://docs.work.com",
                "favIconUrl": "",
                "active": False,
                "pinned": False,
                "audible": False,
                "muted": False,
                "discarded": False,
                "lastAccessed": 500,
                "container": None,
            },
        ]

        ff1 = FakeFirefoxController("Work", "dir.Work", "groups_db", tabs=tabs1, runtime_dir=self.runtime_dir)
        info1 = ff1.start()

        try:
            # 1. Single profile connected
            tabs = fftabs.fetch_tabs()
            self.assertEqual(len(tabs), 2)
            # Ref must be bare ID when only one profile is connected
            self.assertEqual(tabs[0]["ref"], "10")
            self.assertEqual(tabs[1]["ref"], "11")

            # Payload for rofi should NOT contain profile name in tags when single profile
            payload = fftabs.build_payload(tabs, no_icons=True).decode()
            self.assertNotIn("Work/win", payload)
            # Visible tag span has no profile tag
            first_row = payload.split("\n")[0].split("\x00")[0]
            self.assertNotIn("· Work", first_row)
            # Single window -> no "win 1" tag
            self.assertNotIn("win 1", payload)

            # Bare ID resolves cleanly
            sock_p, tid = fftabs.resolve_ref("10")
            self.assertEqual(str(sock_p), info1["sock_path"])
            self.assertEqual(tid, 10)

            # 2. Start second profile ("Personal")
            tabs2 = [
                {
                    "id": 10,  # Duplicate tab id 10 to test ambiguity!
                    "index": 0,
                    "window": {"id": 200, "n": 1, "focused": True, "private": False},
                    "title": "Personal Feed",
                    "url": "https://social.com",
                    "favIconUrl": "",
                    "active": True,
                    "pinned": False,
                    "audible": False,
                    "muted": False,
                    "discarded": False,
                    "lastAccessed": 2000,
                    "container": None,
                },
                {
                    "id": 99,  # Unique tab id 99
                    "index": 1,
                    "window": {"id": 200, "n": 1, "focused": False, "private": False},
                    "title": "Personal Music",
                    "url": "https://music.com",
                    "favIconUrl": "",
                    "active": False,
                    "pinned": False,
                    "audible": False,
                    "muted": False,
                    "discarded": False,
                    "lastAccessed": 1500,
                    "container": None,
                },
            ]

            ff2 = FakeFirefoxController("Personal", "dir.Personal", "groups_db", tabs=tabs2, runtime_dir=self.runtime_dir)
            info2 = ff2.start()

            try:
                # Both profiles connected:
                tabs = fftabs.fetch_tabs()
                self.assertEqual(len(tabs), 4)

                # Refs should now be profile_slug:ID
                refs = {t["ref"] for t in tabs}
                self.assertIn("work:10", refs)
                self.assertIn("work:11", refs)
                self.assertIn("personal:10", refs)
                self.assertIn("personal:99", refs)

                # Multi-profile rofi payload: tags show prefixed window
                payload = fftabs.build_payload(tabs, no_icons=True).decode()
                self.assertIn("Work/win 1", payload)
                self.assertIn("Personal/win 1", payload)

                # Resolve ref by profile:ID
                sp, tid = fftabs.resolve_ref("work:10")
                self.assertEqual(str(sp), info1["sock_path"])
                self.assertEqual(tid, 10)

                sp, tid = fftabs.resolve_ref("personal:10")
                self.assertEqual(str(sp), info2["sock_path"])
                self.assertEqual(tid, 10)

                # Resolve ref by PID:ID (backward compatibility)
                sp, tid = fftabs.resolve_ref(f"{info1['host_pid']}:11")
                self.assertEqual(str(sp), info1["sock_path"])
                self.assertEqual(tid, 11)

                # Bare ID resolution:
                # Tab 99 is unambiguous (only in Personal) -> resolves without error!
                sp, tid = fftabs.resolve_ref("99")
                self.assertEqual(str(sp), info2["sock_path"])
                self.assertEqual(tid, 99)

                # Tab 10 exists in both Work and Personal -> ambiguous!
                err_buf = io.StringIO()
                with redirect_stderr(err_buf), self.assertRaises(SystemExit):
                    fftabs.resolve_ref("10")
                self.assertIn("ambiguous", err_buf.getvalue())

                # Filtering by profile in cmd_list
                class Args:
                    profile = "personal"
                    sort = "window"
                    json = True

                buf = io.StringIO()
                with redirect_stdout(buf):
                    fftabs.cmd_list(Args(), [])
                out = json.loads(buf.getvalue())
                self.assertEqual(len(out), 2)
                for item in out:
                    self.assertEqual(item["profile"], "Personal")
                    self.assertEqual(item["profile_slug"], "personal")
                    self.assertEqual(item["firefox_pid"], info2["fake_pid"])
                    # Filtered output uses bare ID
                    self.assertNotIn(":", item["ref"])

                # Non-json TSV listing
                Args.json = False
                buf = io.StringIO()
                with redirect_stdout(buf):
                    fftabs.cmd_list(Args(), [])
                lines = buf.getvalue().strip().split("\n")
                self.assertEqual(len(lines), 2)
                # TSV has profile column at index 1
                cols = lines[0].split("\t")
                self.assertEqual(cols[1], "Personal")

                # Test switch_to passes firefox_pid to compositor
                with patch.object(fftabs, "focus_firefox_window") as mock_focus:
                    fftabs.switch_to(Path(info1["sock_path"]), 10)
                    self.assertTrue(mock_focus.called)
                    _, kwargs = mock_focus.call_args
                    self.assertEqual(kwargs.get("firefox_pid"), info1["fake_pid"])

            finally:
                ff2.stop()

        finally:
            ff1.stop()

    def test_slug_collision_disambiguation(self):
        # Two profiles with the identical name "Work"
        ff1 = FakeFirefoxController("Work", "dir.Work1", "groups_db", runtime_dir=self.runtime_dir)
        info1 = ff1.start()
        ff2 = FakeFirefoxController("Work", "dir.Work2", "groups_db", runtime_dir=self.runtime_dir)
        info2 = ff2.start()

        try:
            tabs = fftabs.fetch_tabs()
            # Slugs must be suffixed with PID
            expected_slug1 = f"work-{info1['host_pid']}"
            expected_slug2 = f"work-{info2['host_pid']}"

            slugs = {t["_profile_slug"] for t in tabs}
            self.assertIn(expected_slug1, slugs)
            self.assertIn(expected_slug2, slugs)

            # Refs use the disambiguated slugs
            refs = {t["ref"] for t in tabs}
            self.assertIn(f"{expected_slug1}:1", refs)
            self.assertIn(f"{expected_slug2}:1", refs)

            # Resolving with disambiguated slug works
            sp, tid = fftabs.resolve_ref(f"{expected_slug1}:1")
            self.assertEqual(str(sp), info1["sock_path"])
        finally:
            ff1.stop()
            ff2.stop()

    def test_duplicate_host_connections_for_same_profile(self):
        # Two hosts connected to the exact SAME profile instance (same profile dirname)
        ff1 = FakeFirefoxController("Work", "dir.WorkSame", "groups_db", runtime_dir=self.runtime_dir)
        info1 = ff1.start()
        ff2 = FakeFirefoxController("Work", "dir.WorkSame", "groups_db", runtime_dir=self.runtime_dir)
        info2 = ff2.start()

        try:
            tabs = fftabs.fetch_tabs()
            # Must return only 1 set of tabs, NOT 2 (no duplication!)
            self.assertEqual(len(tabs), 1)
            # Since only 1 distinct profile is active, refs should be bare IDs
            self.assertEqual(tabs[0]["ref"], "1")

            # Bare ID resolves cleanly without ambiguity error
            sp, tid = fftabs.resolve_ref("1")
            self.assertIn(str(sp), (info1["sock_path"], info2["sock_path"]))
            self.assertEqual(tid, 1)

            # Profile:ID resolution also works without ambiguous profile error
            sp2, tid2 = fftabs.resolve_ref("work:1")
            self.assertIn(str(sp2), (info1["sock_path"], info2["sock_path"]))
            self.assertEqual(tid2, 1)

            # Check status output marks duplicate
            class StatusArgs:
                manifest_dir = None
            buf = io.StringIO()
            with redirect_stdout(buf):
                fftabs.cmd_status(StatusArgs(), [])
            status_txt = buf.getvalue()
            self.assertIn("(duplicate connection)", status_txt)
        finally:
            ff1.stop()
            ff2.stop()


    def test_rofi_with_stub(self):
        # Test rofi execution with stub script
        stub_dir = tempfile.mkdtemp(prefix="rofi_test_stub_")
        stub_script = REPO_ROOT / "tests" / "rofi_stub.sh"
        tabs_data = [
            {
                "id": 42,
                "index": 0,
                "window": {"id": 1, "n": 1, "focused": True, "private": False},
                "title": "Tab 42",
                "url": "https://example.com/42",
                "favIconUrl": "",
                "active": True,
                "pinned": False,
                "audible": False,
                "muted": False,
                "discarded": False,
                "lastAccessed": 1000,
                "container": None,
            }
        ]

        ff = FakeFirefoxController("Work", "dir.Work", "groups_db", tabs=tabs_data, runtime_dir=self.runtime_dir)
        info = ff.start()

        try:
            bin_dir = tempfile.mkdtemp(prefix="rofi_bin_")
            rofi_link = Path(bin_dir) / "rofi"
            os.symlink(stub_script, rofi_link)

            old_path = os.environ.get("PATH", "")
            env_override = {
                "PATH": f"{bin_dir}:{old_path}",
                "ROFI_STUB_DIR": stub_dir,
                "ROFI_STUB_SELECTION": "0",
                "ROFI_STUB_EXIT": "0",
            }

            class RofiArgs:
                sort = "recent"
                previous = True
                no_icons = True
                no_fetch = True
                profile = None

            with patch.dict(os.environ, env_override), patch.object(fftabs, "switch_to") as mock_switch:
                ret = fftabs.cmd_rofi(RofiArgs(), [])
                self.assertEqual(ret, 0)
                self.assertTrue(mock_switch.called)

            # Check recorded argv
            argv = (Path(stub_dir) / "argv").read_text().splitlines()
            self.assertIn("-dmenu", argv)
            self.assertIn("-selected-row", argv)

            # Check recorded stdin
            stdin_content = (Path(stub_dir) / "stdin").read_text()
            self.assertIn("Tab 42", stdin_content)

            shutil.rmtree(bin_dir, ignore_errors=True)
            shutil.rmtree(stub_dir, ignore_errors=True)
        finally:
            ff.stop()


class TestTabOrdering(unittest.TestCase):
    def setUp(self):
        # Window 1: older tabs
        self.t1_1 = {
            "id": 1, "index": 0, "title": "W1 Tab 0", "url": "https://a.com",
            "lastAccessed": 1000, "window": {"id": 101, "n": 1, "focused": False},
            "_profile_slug": "prof1"
        }
        self.t1_2 = {
            "id": 2, "index": 1, "title": "W1 Tab 1", "url": "https://b.com",
            "lastAccessed": 2000, "window": {"id": 101, "n": 1, "focused": False},
            "_profile_slug": "prof1"
        }
        # Window 2: newer tabs
        self.t2_1 = {
            "id": 3, "index": 0, "title": "W2 Tab 0", "url": "https://c.com",
            "lastAccessed": 3000, "window": {"id": 102, "n": 2, "focused": False},
            "_profile_slug": "prof1"
        }
        self.t2_2 = {
            "id": 4, "index": 1, "title": "W2 Tab 1", "url": "https://d.com",
            "lastAccessed": 4000, "window": {"id": 102, "n": 2, "focused": False},
            "_profile_slug": "prof1"
        }
        self.all_tabs = [self.t1_1, self.t1_2, self.t2_1, self.t2_2]

    def test_window_recent_orders_mru_window_first_and_tabs_mru(self):
        # Window 2 has max access 4000 > Window 1 max access 2000.
        # Window 2 must come first, and within Window 2: t2_2 (4000) before t2_1 (3000).
        # Within Window 1: t1_2 (2000) before t1_1 (1000).
        res = fftabs.ordered(self.all_tabs, "window-recent")
        self.assertEqual([t["id"] for t in res], [4, 3, 2, 1])

        # "window" is an alias for "window-recent"
        res_alias = fftabs.ordered(self.all_tabs, "window")
        self.assertEqual([t["id"] for t in res_alias], [4, 3, 2, 1])

    def test_focused_window_has_highest_priority(self):
        # Even if Window 1 has lower timestamps, if it is focused, it must be first
        t1_1_foc = dict(self.t1_1, window={"id": 101, "n": 1, "focused": True})
        t1_2_foc = dict(self.t1_2, window={"id": 101, "n": 1, "focused": True})
        tabs = [self.t2_1, self.t2_2, t1_1_foc, t1_2_foc]

        res = fftabs.ordered(tabs, "window-recent")
        # Window 1 tabs first (t1_2 with 2000, t1_1 with 1000), then Window 2 (t2_2 with 4000, t2_1 with 3000)
        self.assertEqual([t["id"] for t in res], [2, 1, 4, 3])

    def test_window_index_mode(self):
        # Window 2 has max timestamp 4000 > Window 1, so Window 2 is first.
        # But tabs inside are ordered by index: t2_1 (idx 0) before t2_2 (idx 1).
        res = fftabs.ordered(self.all_tabs, "window-index")
        self.assertEqual([t["id"] for t in res], [3, 4, 1, 2])

    def test_pure_recent_mode(self):
        # Global flat MRU order: 4000 (t2_2), 3000 (t2_1), 2000 (t1_2), 1000 (t1_1)
        res = fftabs.ordered(self.all_tabs, "recent")
        self.assertEqual([t["id"] for t in res], [4, 3, 2, 1])

        # Interleaved test:
        t_mid = {
            "id": 5, "index": 2, "title": "W1 Tab 2", "url": "https://e.com",
            "lastAccessed": 3500, "window": {"id": 101, "n": 1, "focused": False},
            "_profile_slug": "prof1"
        }
        interleaved = [self.t1_1, self.t1_2, self.t2_1, self.t2_2, t_mid]
        # In recent: 4000 (t2_2), 3500 (t_mid), 3000 (t2_1), 2000 (t1_2), 1000 (t1_1)
        res_int = fftabs.ordered(interleaved, "recent")
        self.assertEqual([t["id"] for t in res_int], [4, 5, 3, 2, 1])

        # But in window-recent: Window 2 still has max 4000, Window 1 has max 3500:
        # Window 2 (4, 3), Window 1 (5, 2, 1)
        res_win = fftabs.ordered(interleaved, "window-recent")
        self.assertEqual([t["id"] for t in res_win], [4, 3, 5, 2, 1])

    def test_window_num_mode(self):
        # Orders by static window n: Window 1 (n=1) then Window 2 (n=2), tabs by index
        res = fftabs.ordered(self.all_tabs, "window-num")
        self.assertEqual([t["id"] for t in res], [1, 2, 3, 4])

    def test_empty_tabs(self):
        self.assertEqual(fftabs.ordered([], "window-recent"), [])
        self.assertEqual(fftabs.ordered([], "recent"), [])


class TestScopedTabClosing(unittest.TestCase):
    def setUp(self):
        # Window 101 with 5 tabs (indices 0 to 4)
        self.tabs = [
            {"id": 10, "index": 0, "title": "Tab 0 (pinned)", "pinned": True, "window": {"id": 101, "n": 1}},
            {"id": 11, "index": 1, "title": "Tab 1", "pinned": False, "window": {"id": 101, "n": 1}},
            {"id": 12, "index": 2, "title": "Tab 2 (target)", "pinned": False, "window": {"id": 101, "n": 1}},
            {"id": 13, "index": 3, "title": "Tab 3", "pinned": False, "window": {"id": 101, "n": 1}},
            {"id": 14, "index": 4, "title": "Tab 4", "pinned": False, "window": {"id": 101, "n": 1}},
            # Window 102 with 1 tab
            {"id": 20, "index": 0, "title": "Other Win Tab", "pinned": False, "window": {"id": 102, "n": 2}},
        ]
        self.target = self.tabs[2]  # Tab 2 (id: 12, index: 2)

    def test_compute_scoped_others(self):
        # Others in Window 101 (skipping pinned tab 0 and target tab 2)
        to_close = fftabs.compute_scoped_tabs(self.tabs, self.target, "others", keep_pinned=True)
        self.assertEqual([t["id"] for t in to_close], [11, 13, 14])

        # If keep_pinned=False, includes tab 0
        to_close_pinned = fftabs.compute_scoped_tabs(self.tabs, self.target, "others", keep_pinned=False)
        self.assertEqual([t["id"] for t in to_close_pinned], [10, 11, 13, 14])

    def test_compute_scoped_right(self):
        # Tabs to the right of Tab 2: Tab 3 and Tab 4
        to_close = fftabs.compute_scoped_tabs(self.tabs, self.target, "right", keep_pinned=True)
        self.assertEqual([t["id"] for t in to_close], [13, 14])

    def test_compute_scoped_left(self):
        # Tabs to the left of Tab 2: Tab 1 (Tab 0 is pinned, so excluded)
        to_close = fftabs.compute_scoped_tabs(self.tabs, self.target, "left", keep_pinned=True)
        self.assertEqual([t["id"] for t in to_close], [11])

        # If keep_pinned=False, includes Tab 0
        to_close_pinned = fftabs.compute_scoped_tabs(self.tabs, self.target, "left", keep_pinned=False)
        self.assertEqual([t["id"] for t in to_close_pinned], [10, 11])


class TestUrlAndSearchResolution(unittest.TestCase):
    def test_explicit_urls(self):
        self.assertEqual(fftabs.resolve_url_or_search("https://example.com"), "https://example.com")
        self.assertEqual(fftabs.resolve_url_or_search("http://localhost:8080/foo"), "http://localhost:8080/foo")
        self.assertEqual(fftabs.resolve_url_or_search("about:config"), "about:config")

    def test_domain_names(self):
        self.assertEqual(fftabs.resolve_url_or_search("github.com"), "https://github.com")
        self.assertEqual(fftabs.resolve_url_or_search("news.ycombinator.com/item?id=123"), "https://news.ycombinator.com/item?id=123")
        self.assertEqual(fftabs.resolve_url_or_search("localhost:3000"), "https://localhost:3000")

    def test_search_queries(self):
        res = fftabs.resolve_url_or_search("python asyncio tutorial")
        self.assertEqual(res, "https://duckduckgo.com/?q=python+asyncio+tutorial")

    def test_empty_string(self):
        self.assertEqual(fftabs.resolve_url_or_search(""), "about:newtab")


class TestHistoryCache(unittest.TestCase):
    def test_record_and_merge_history(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("fftabs.cache_dir", return_value=Path(td)):
                tabs = [
                    {"url": "https://a.com", "title": "A", "favIconUrl": "", "lastAccessed": 1000},
                    {"url": "https://b.com", "title": "B", "favIconUrl": "", "lastAccessed": 2000},
                ]
                fftabs.record_history(tabs)
                hfile = Path(td) / "history.json"
                self.assertTrue(hfile.exists())
                data = json.loads(hfile.read_text())
                self.assertEqual(len(data), 2)
                # B has higher lastAccessed, should be first
                self.assertEqual(data[0]["url"], "https://b.com")

                # Test fetch_combined_history reading from cache
                with patch("fftabs.sockets", return_value=[]):
                    combined = fftabs.fetch_combined_history()
                    self.assertEqual(len(combined), 2)
                    self.assertEqual(combined[0]["url"], "https://b.com")

                    # Test query filtering
                    filtered = fftabs.fetch_combined_history(query="b.com")
                    self.assertEqual(len(filtered), 1)
                    self.assertEqual(filtered[0]["url"], "https://b.com")


class TestConfiguration(unittest.TestCase):
    def test_default_config_structure(self):
        cfg = fftabs.load_config(Path("/nonexistent/config.toml"))
        self.assertEqual(cfg["general"]["default_sort"], "window-recent")
        self.assertIn("duckduckgo", cfg["general"]["search_url"])
        self.assertTrue(cfg["history"]["enabled"])
        self.assertEqual(cfg["keybindings"]["close_tab"], "Alt+d")
        self.assertEqual(cfg["keybindings"]["close_others"], "Alt+o")

    def test_toml_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_p = Path(td) / "config.toml"
            cfg_p.write_text("""
[general]
default_sort = "recent"
search_url = "https://google.com/search?q={query}"

[history]
enabled = false
exclude_profiles = ["secret"]
exclude_url_patterns = ["^https?://internal\\\\.net"]

[keybindings]
close_tab = "Ctrl+q"
close_others = ""
""")
            cfg = fftabs.load_config(cfg_p)
            self.assertEqual(cfg["general"]["default_sort"], "recent")
            self.assertEqual(cfg["general"]["search_url"], "https://google.com/search?q={query}")
            self.assertFalse(cfg["history"]["enabled"])
            self.assertEqual(cfg["history"]["exclude_profiles"], ["secret"])
            self.assertEqual(cfg["keybindings"]["close_tab"], "Ctrl+q")
            self.assertEqual(cfg["keybindings"]["close_others"], "")
            # Untouched keys remain at default
            self.assertEqual(cfg["keybindings"]["close_right"], "Alt+r")

    def test_history_exclude_profiles_and_patterns(self):
        with tempfile.TemporaryDirectory() as td:
            mock_cfg = {
                "history": {
                    "enabled": True,
                    "enable_session_cache": True,
                    "exclude_profiles": ["private-prof"],
                    "exclude_url_patterns": ["^https?://secret\\.local"],
                    "history_file": str(Path(td) / "hist.json"),
                    "max_entries": 100,
                }
            }
            with patch("fftabs.get_config", return_value=mock_cfg):
                tabs = [
                    {"url": "https://allowed.com", "title": "Allowed", "_profile_name": "work"},
                    {"url": "https://secret.local/page", "title": "Secret", "_profile_name": "work"},
                    {"url": "https://other.com", "title": "Private Tab", "_profile_name": "private-prof"},
                ]
                fftabs.record_history(tabs)
                hfile = Path(td) / "hist.json"
                self.assertTrue(hfile.exists())
                recorded = json.loads(hfile.read_text())
                urls = [r["url"] for r in recorded]
                self.assertEqual(urls, ["https://allowed.com"])

    def test_config_init(self):
        with tempfile.TemporaryDirectory() as td:
            with patch("fftabs.config_dir", return_value=Path(td)):
                class Args:
                    init = True
                    path = False
                    show = False
                    force = False

                ret = fftabs.cmd_config(Args(), [])
                self.assertEqual(ret, 0)
                cfg_file = Path(td) / "config.toml"
                self.assertTrue(cfg_file.exists())
                import tomllib
                parsed = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                self.assertIn("general", parsed)
                self.assertIn("keybindings", parsed)


if __name__ == "__main__":
    unittest.main()
