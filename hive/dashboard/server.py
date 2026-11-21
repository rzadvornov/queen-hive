"""`hive dashboard`: a read-only local web app over ~/.hive (runs, live events, comparisons, projects, models)."""

import argparse
import asyncio
import json
import time
import webbrowser
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.middleware import Middleware
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from hive import memory, models

STATIC = Path(__file__).parent / "static"
LIVE_WINDOW = 6 * 3600   # a run without run_end that was touched this recently counts as live


# --- data access --------------------------------------------------------------

def _project(pid: str) -> Path:
    pdir = memory.hive_home() / "projects" / pid
    if not pdir.is_dir() or "/" in pid or pid.startswith("."):
        raise FileNotFoundError(pid)
    return pdir


def _run_dir(pid: str, rid: str) -> Path:
    run_dir = _project(pid) / "runs" / rid
    if not run_dir.is_dir() or "/" in rid or rid.startswith("."):
        raise FileNotFoundError(rid)
    return run_dir


def _events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


_ROWS: dict[Path, tuple[int, dict | None]] = {}   # run.json → (mtime, row): finished runs rarely change


def _brief(pdir: Path, run_dir: Path) -> dict | None:
    """One row for the runs table: from run.json when finished, else from the event log."""
    record_path = run_dir / "run.json"
    try:
        stamp = record_path.stat().st_mtime_ns
    except OSError:
        return _live_brief(pdir, run_dir)
    cached = _ROWS.get(record_path)
    if cached and cached[0] == stamp:
        return cached[1]
    row = _finished_brief(pdir, run_dir, record_path)
    _ROWS[record_path] = (stamp, row)
    return row


def _finished_brief(pdir: Path, run_dir: Path, record_path: Path) -> dict | None:
    from hive.stats import baseline

    try:
        r = json.loads(record_path.read_text())
    except ValueError:
        return None
    base = None
    found = baseline(r)
    if found and found[1] and r["hive"].get("cost_usd"):
        base = {"name": found[0], "cost_usd": found[1], "measured": found[2]}
    return {
        "project": pdir.name, "id": run_dir.name, "root": r["folders"][0], "goal": r["goal"],
        "queen": r["queen"], "workers": r["workers"], "mode": r["mode"], "status": r["status"],
        "started_at": r["started_at"], "ended_at": r.get("ended_at"), "cost_usd": r["hive"].get("cost_usd"),
        "passed": r["acceptance"]["passed"], "compare": bool(r.get("compare")), "baseline": base, "live": False,
    }


def _live_brief(pdir: Path, run_dir: Path) -> dict | None:
    events = _events(run_dir)
    start = next((e for e in events if e["kind"] == "run_start"), None)
    if not start:
        return None
    last = events[-1]["ts"]
    cost = next((e.get("cost_usd") for e in reversed(events) if e["kind"] == "turn_end"), None)
    return {
        "project": pdir.name, "id": run_dir.name, "root": (start.get("folders") or [""])[0], "goal": start.get("goal", ""),
        "queen": {"key": start.get("queen"), "name": _model_name(start.get("queen"))},
        "workers": {"key": start.get("workers"), "name": _model_name(start.get("workers"))},
        "mode": start.get("mode"), "status": "running" if time.time() - last < LIVE_WINDOW else "abandoned",
        "started_at": start["ts"], "ended_at": None, "cost_usd": cost, "passed": None, "compare": bool(start.get("compare")),
        "baseline": None, "live": time.time() - last < LIVE_WINDOW,
    }


def _model_name(key: str | None) -> str:
    model = models.find(key or "") if key else None
    return model.name if model else (key or "?")


def all_runs() -> list[dict]:
    rows = []
    for pdir in memory.all_projects():
        for run_dir in (pdir / "runs").iterdir() if (pdir / "runs").exists() else []:
            if run_dir.is_dir():
                row = _brief(pdir, run_dir)
                if row:
                    rows.append(row)
    return sorted(rows, key=lambda r: r["started_at"], reverse=True)


# --- routes -------------------------------------------------------------------

async def index(request: Request) -> Response:
    return FileResponse(STATIC / "index.html")


async def api_runs(request: Request) -> Response:
    return JSONResponse(all_runs())


async def api_run(request: Request) -> Response:
    try:
        run_dir = _run_dir(request.path_params["pid"], request.path_params["rid"])
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    record_path = run_dir / "run.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else None
    return JSONResponse({"record": record, "events": _events(run_dir), "project": request.path_params["pid"],
                         "id": run_dir.name})


async def api_stream(request: Request) -> Response:
    """Server-sent events: every new line of the run's event log as it is written."""
    try:
        run_dir = _run_dir(request.path_params["pid"], request.path_params["rid"])
    except FileNotFoundError:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = run_dir / "events.jsonl"
    offset = int(request.query_params.get("offset", "0"))

    async def stream():
        position = offset
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            if path.exists():
                with path.open() as handle:
                    handle.seek(position)
                    chunk = handle.read()
                    position = handle.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        idle = 0
                        yield f"data: {line}\n\n"
                        if '"kind": "run_end"' in line:
                            yield "event: end\ndata: {}\n\n"
                            return
            idle += 1
            if idle % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def api_projects(request: Request) -> Response:
    rows = []
    for pdir in memory.all_projects():
        runs = [r for r in (pdir / "runs").iterdir() if r.is_dir()] if (pdir / "runs").exists() else []
        rows.append({"id": pdir.name, "root": str(memory.project_root(pdir) or ""), "runs": len(runs),
                     "files": {name: memory.read(pdir, name) for name in memory.MEMORY_FILES},
                     "path": str(pdir)})
    return JSONResponse(rows)


async def api_models(request: Request) -> Response:
    state = memory.load_state()
    return JSONResponse({
        "prices_as_of": models.PRICES_AS_OF,
        "last_queen": state.get("last_queen"),
        "models": [{"key": m.key, "id": m.id, "name": m.name, "input": m.input, "output": m.output,
                    "cache_read": m.cache_read, "role": "queen" if m.queen_effort else "bees", "note": m.note,
                    "access": models.access(state).get(m.key)} for m in models.catalog()],
    })


async def api_models_check(request: Request) -> Response:
    await models.check_access()
    return await api_models(request)


async def export(request: Request) -> Response:
    """A self-contained HTML copy of one run's report: data and code inlined, works offline."""
    try:
        run_dir = _run_dir(request.path_params["pid"], request.path_params["rid"])
    except FileNotFoundError:
        return HTMLResponse("not found", status_code=404)
    record_path = run_dir / "run.json"
    if not record_path.exists():
        return HTMLResponse("This run hasn't finished yet.", status_code=409)
    payload = {"record": json.loads(record_path.read_text()), "events": _events(run_dir),
               "project": request.path_params["pid"], "id": run_dir.name}
    html = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()
    js = (STATIC / "app.js").read_text()
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="/static/style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="/static/app.js"></script>',
                        f"<script>window.HIVE_EXPORT = {data};</script>\n<script>{js}</script>")
    name = f"hive-run-{run_dir.name}.html"
    return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="{name}"'})


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class LocalOnly:
    """Serve only requests addressed to this machine, and POSTs only from the dashboard's own pages.

    The Host check stops DNS rebinding (a web page whose domain points at 127.0.0.1 reading your runs);
    the Origin check stops other sites from triggering paid model checks.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            host = headers.get("host", "")
            origin = headers.get("origin")
            same_origin = origin in (f"http://{host}", f"https://{host}")
            if host.rsplit(":", 1)[0] not in LOCAL_HOSTS or (scope["method"] not in ("GET", "HEAD") and not same_origin):
                await PlainTextResponse("forbidden: the hive dashboard only answers its own pages on localhost",
                                        status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app() -> Starlette:
    return Starlette(middleware=[Middleware(LocalOnly)], routes=[
        Route("/", index),
        Route("/api/runs", api_runs),
        Route("/api/runs/{pid}/{rid}", api_run),
        Route("/api/runs/{pid}/{rid}/stream", api_stream),
        Route("/api/runs/{pid}/{rid}/export", export),
        Route("/api/projects", api_projects),
        Route("/api/models", api_models),
        Route("/api/models/check", api_models_check, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])


def serve(port: int, open_browser: bool = False) -> None:
    """Run the server in this process until Ctrl-C or SIGTERM."""
    import uvicorn

    if open_browser:
        webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":  # the background process started by `hive dashboard`
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7777)
    serve(parser.parse_args().port)
