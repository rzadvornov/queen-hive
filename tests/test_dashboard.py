import json
import time

from starlette.testclient import TestClient

from hive import memory
from hive.dashboard.server import create_app


def make_run(root, finished: bool):
    pdir = memory.ensure_project(root)
    run_dir = pdir / "runs" / ("20261115-000000-done" if finished else "20261115-000001-live")
    run_dir.mkdir(parents=True)
    now = time.time()
    events = [
        {"ts": now, "kind": "run_start", "goal": "add combo", "queen": "opus-5.5", "workers": "haiku-5.5", "mode": "auto",
         "folders": [str(root)]},
        {"ts": now + 1, "kind": "dispatch", "id": "a1", "label": "B1", "agent": "haiku-hive:builder", "stage": "build",
         "description": "B1 combo", "prompt": "Goal: x\nDone when: npm test"},
    ]
    (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    if finished:
        record = {
            "goal": "add combo", "folders": [str(root)], "queen": {"key": "opus-5.5", "name": "Claude Opus 5.5"},
            "workers": {"key": "haiku-5.5", "name": "Claude Haiku 5.5"}, "mode": "auto", "status": "done",
            "started_at": now, "ended_at": now + 60, "hive": {"cost_usd": 0.5}, "acceptance": {"passed": True},
            "compare": [], "estimates": [{"model": "opus-5.5", "name": "Claude Opus 5.5", "cost_usd": 1.0}],
        }
        (run_dir / "run.json").write_text(json.dumps(record))
    return pdir, run_dir


def test_runs_live_and_export(tmp_path):
    root = tmp_path / "shop"
    root.mkdir()
    pdir, done = make_run(root, finished=True)
    _, live = make_run(root, finished=False)
    client = TestClient(create_app(), base_url="http://localhost:7777")

    runs = client.get("/api/runs").json()
    by_id = {r["id"]: r for r in runs}
    assert by_id[live.name]["live"] is True and by_id[live.name]["status"] == "running"
    assert by_id[done.name]["passed"] is True and by_id[done.name]["baseline"]["cost_usd"] == 1.0

    detail = client.get(f"/api/runs/{pdir.name}/{done.name}").json()
    assert detail["record"]["goal"] == "add combo" and len(detail["events"]) == 2

    page = client.get(f"/api/runs/{pdir.name}/{done.name}/export")
    assert page.status_code == 200 and "window.HIVE_EXPORT" in page.text and "/static/" not in page.text
    assert client.get(f"/api/runs/{pdir.name}/{live.name}/export").status_code == 409
    assert client.get(f"/api/runs/{pdir.name}/../../etc").status_code == 404

    projects = client.get("/api/projects").json()
    assert projects[0]["root"] == str(root.resolve()) and "profile.md" in projects[0]["files"]
    assert any(m["key"] == "opus-5.5" for m in client.get("/api/models").json()["models"])


def test_background_up_and_down(capsys):
    import socket

    from hive.dashboard import process

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process.up(port, open_browser=False)
    info = process.running()
    try:
        assert info and info["port"] == port and process._port_open(port)
        process.up(port, open_browser=False)                    # second start reuses the running one
        assert process.running()["pid"] == info["pid"]
    finally:
        process.down()
    assert process.running() is None and not process._port_open(port)
    assert not process.pid_path().exists()
    out = capsys.readouterr().out
    assert "already running" in out and "stopped" in out


def test_dashboard_answers_only_local_pages(monkeypatch):
    from hive import models

    async def no_probe(keys=None):
        return {}

    monkeypatch.setattr(models, "check_access", no_probe)
    local = TestClient(create_app(), base_url="http://localhost:7777")
    assert local.get("/api/models").status_code == 200
    assert TestClient(create_app(), base_url="http://evil.example").get("/api/projects").status_code == 403   # DNS rebinding
    assert local.post("/api/models/check").status_code == 403                                      # no Origin
    assert local.post("/api/models/check", headers={"origin": "https://evil.example"}).status_code == 403
    assert local.post("/api/models/check", headers={"origin": "http://localhost:7777"}).status_code == 200
