"""The dashboard as a background process: `hive dashboard` starts it, `hive dashboard down` stops it."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from hive import memory

SERVER_MODULE = "hive.dashboard.server"


def pid_path() -> Path:
    return memory.hive_home() / "dashboard.json"


def log_path() -> Path:
    return memory.hive_home() / "dashboard.log"


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _is_dashboard(pid: int) -> bool:
    """True if `pid` is alive and is our server, so a recycled pid is never killed."""
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return SERVER_MODULE in out.stdout


def running() -> dict | None:
    """The running dashboard's {pid, port, url}, or None. Clears a stale pid file."""
    try:
        info = json.loads(pid_path().read_text())
    except (OSError, ValueError):
        return None
    if _is_dashboard(info.get("pid", -1)):
        return info
    pid_path().unlink(missing_ok=True)
    return None


def up(port: int, open_browser: bool) -> None:
    info = running()
    if info:
        print(f"🐝 hive dashboard already running on {info['url']} (pid {info['pid']}); `hive dashboard down` stops it")
    else:
        if _port_open(port):
            raise SystemExit(f"port {port} is already in use; pick another with --port")
        memory.hive_home().mkdir(parents=True, exist_ok=True)
        with open(log_path(), "ab") as log:
            proc = subprocess.Popen([sys.executable, "-m", SERVER_MODULE, "--port", str(port)],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        deadline = time.time() + 10
        while not _port_open(port):
            if proc.poll() is not None or time.time() > deadline:
                if proc.poll() is None:
                    proc.terminate()
                raise SystemExit(f"the dashboard didn't start; see {log_path()}")
            time.sleep(0.1)
        info = {"pid": proc.pid, "port": port, "url": f"http://localhost:{port}"}
        pid_path().write_text(json.dumps(info))
        print(f"🐝 hive dashboard on {info['url']} (pid {proc.pid}); `hive dashboard down` stops it")
    if open_browser:
        webbrowser.open(info["url"])


def down() -> None:
    info = running()
    if not info:
        print("hive dashboard is not running")
        return
    pid = info["pid"]
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while _is_dashboard(pid) and time.time() < deadline:
        time.sleep(0.1)
    if _is_dashboard(pid):
        os.kill(pid, signal.SIGKILL)
    pid_path().unlink(missing_ok=True)
    print(f"🐝 hive dashboard stopped (pid {pid})")


def status() -> None:
    info = running()
    print(f"🐝 hive dashboard running on {info['url']} (pid {info['pid']})" if info else "hive dashboard is not running")
