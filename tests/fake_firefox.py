#!/usr/bin/env python3
"""Fake Firefox process that mimics a running Firefox instance.

- Creates a temp Firefox directory with Profile Groups DB or profiles.ini.
- Opens and holds .parentlock in its process.
- Launches `fftabs host` as a child so child's ppid is this process.
- Answers native-messaging requests over stdin/stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FFTABS_SCRIPT = REPO_ROOT / "fftabs"


def setup_temp_profile(
    root: Path,
    profile_name: str,
    profile_dirname: str,
    db_mode: str = "groups_db",
) -> tuple[Path, Path]:
    profile_dir = root / profile_dirname
    profile_dir.mkdir(parents=True, exist_ok=True)
    lock_file = profile_dir / ".parentlock"
    lock_file.write_text("")

    if db_mode == "groups_db":
        pg_dir = root / "Profile Groups"
        pg_dir.mkdir(parents=True, exist_ok=True)
        db_path = pg_dir / "test_store.sqlite"
        con = sqlite3.connect(str(db_path))
        try:
            con.execute(
                "CREATE TABLE Profiles (id INTEGER PRIMARY KEY, path TEXT, name TEXT, avatar TEXT, themeId TEXT, themeFg TEXT, themeBg TEXT)"
            )
            con.execute(
                "INSERT INTO Profiles (path, name) VALUES (?, ?)",
                (profile_dirname, profile_name),
            )
            con.commit()
        finally:
            con.close()
    elif db_mode == "ini":
        ini_path = root / "profiles.ini"
        ini_path.write_text(
            f"[General]\nStartWithLastProfile=1\nVersion=2\n\n"
            f"[Profile0]\nName={profile_name}\nIsRelative=1\nPath={profile_dirname}\nDefault=1\n"
        )
    return profile_dir, lock_file


def run_fake_firefox(
    profile_name: str,
    profile_dirname: str,
    db_mode: str = "groups_db",
    tabs: list[dict] | None = None,
    ready_file: str | None = None,
    runtime_dir_override: str | None = None,
) -> None:
    tabs = tabs or [
        {
            "id": 1,
            "index": 0,
            "window": {"id": 1, "n": 1, "focused": True, "private": False},
            "title": f"Tab 1 ({profile_name})",
            "url": f"https://example.com/{profile_name}/1",
            "favIconUrl": "",
            "active": True,
            "pinned": False,
            "audible": False,
            "muted": False,
            "discarded": False,
            "lastAccessed": time.time() * 1000,
            "container": None,
        }
    ]

    temp_dir = tempfile.TemporaryDirectory(prefix="fake_firefox_")
    root = Path(temp_dir.name)
    _, lock_file = setup_temp_profile(root, profile_name, profile_dirname, db_mode)

    # Keep lock file open in this process
    lock_fd = open(lock_file, "r+")

    env = dict(os.environ)
    if runtime_dir_override:
        env["XDG_RUNTIME_DIR"] = runtime_dir_override

    # Spawn `fftabs host` as child so its ppid is this process's pid
    host_proc = subprocess.Popen(
        [sys.executable, str(FFTABS_SCRIPT), "host"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    rt = Path(runtime_dir_override) if runtime_dir_override else Path(env.get("XDG_RUNTIME_DIR", f"/tmp/fftabs-{os.getuid()}"))
    sock_path = rt / f"fftabs-{host_proc.pid}.sock"

    stop_event = threading.Event()

    def handle_sigterm(*_):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    # Native messaging loop
    def native_io():
        stdin = host_proc.stdout
        stdout = host_proc.stdin
        while not stop_event.is_set():
            try:
                hdr = stdin.read(4)
                if len(hdr) < 4:
                    break
                (n,) = struct.unpack("=I", hdr)
                body = stdin.read(n)
                if len(body) < n:
                    break
                msg = json.loads(body.decode("utf-8"))
                cmd = msg.get("cmd")
                rid = msg.get("id")

                if cmd == "ping":
                    res = "pong"
                elif cmd == "list":
                    res = tabs
                elif cmd == "switch":
                    tid = msg.get("tabId")
                    matched = next((t for t in tabs if t["id"] == tid), tabs[0] if tabs else {})
                    res = {"windowId": matched.get("window", {}).get("id", 1), "title": matched.get("title", "")}
                elif cmd == "close":
                    res = True
                else:
                    res = None

                reply = {"id": rid, "ok": True, "result": res}
                data = json.dumps(reply, separators=(",", ":")).encode("utf-8")
                stdout.write(struct.pack("=I", len(data)) + data)
                stdout.flush()
            except Exception:
                break

    t = threading.Thread(target=native_io, daemon=True)
    t.start()

    # Wait for socket to be created
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if sock_path.exists():
            break
        time.sleep(0.05)

    info = {
        "fake_pid": os.getpid(),
        "host_pid": host_proc.pid,
        "sock_path": str(sock_path),
        "profile_name": profile_name,
        "profile_dir": str(root / profile_dirname),
    }

    if ready_file:
        Path(ready_file).write_text(json.dumps(info))
    else:
        print(json.dumps(info), flush=True)

    # Keep alive until stopped
    while not stop_event.is_set():
        if host_proc.poll() is not None:
            break
        time.sleep(0.1)

    # Cleanup
    try:
        host_proc.terminate()
        host_proc.wait(timeout=2)
    except Exception:
        host_proc.kill()

    lock_fd.close()
    temp_dir.cleanup()


class FakeFirefoxController:
    """Helper to start and stop fake Firefox processes from test suites."""

    def __init__(
        self,
        profile_name: str,
        profile_dirname: str,
        db_mode: str = "groups_db",
        tabs: list[dict] | None = None,
        runtime_dir: str | None = None,
    ):
        self.profile_name = profile_name
        self.profile_dirname = profile_dirname
        self.db_mode = db_mode
        self.tabs = tabs
        self.runtime_dir = runtime_dir
        self.proc: subprocess.Popen | None = None
        self.info: dict | None = None

    def start(self, timeout: float = 6.0) -> dict:
        ready_tmp = tempfile.NamedTemporaryFile(delete=False)
        ready_path = ready_tmp.name
        ready_tmp.close()
        os.unlink(ready_path)

        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--profile-name",
            self.profile_name,
            "--profile-dirname",
            self.profile_dirname,
            "--db-mode",
            self.db_mode,
            "--ready-file",
            ready_path,
        ]
        if self.tabs:
            cmd += ["--tabs-json", json.dumps(self.tabs)]
        if self.runtime_dir:
            cmd += ["--runtime-dir", self.runtime_dir]

        self.proc = subprocess.Popen(cmd)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if Path(ready_path).exists():
                try:
                    self.info = json.loads(Path(ready_path).read_text())
                    os.unlink(ready_path)
                    return self.info
                except Exception:
                    pass
            time.sleep(0.05)
        if Path(ready_path).exists():
            os.unlink(ready_path)
        raise TimeoutError(f"Fake Firefox {self.profile_name} did not become ready in {timeout}s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2.0)
        # Verify socket cleanup
        if self.info and "sock_path" in self.info:
            p = Path(self.info["sock_path"])
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-name", required=True)
    parser.add_argument("--profile-dirname", required=True)
    parser.add_argument("--db-mode", default="groups_db")
    parser.add_argument("--tabs-json", default=None)
    parser.add_argument("--ready-file", default=None)
    parser.add_argument("--runtime-dir", default=None)
    args = parser.parse_args()

    parsed_tabs = json.loads(args.tabs_json) if args.tabs_json else None
    run_fake_firefox(
        profile_name=args.profile_name,
        profile_dirname=args.profile_dirname,
        db_mode=args.db_mode,
        tabs=parsed_tabs,
        ready_file=args.ready_file,
        runtime_dir_override=args.runtime_dir,
    )
