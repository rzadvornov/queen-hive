"""Print the facts of a project's last recorded hive run, for the waggle retro.

    python3 lastrun.py DIR

Stdlib only. Reads the run record and event log from the project's hive memory folder.
"""

import json
import sys
from pathlib import Path

from hivecore import project_dir


def last_run(root: str | Path) -> Path | None:
    records = sorted((project_dir(root) / "runs").glob("*/run.json"))
    return records[-1] if records else None


def facts(record_path: Path) -> str:
    record = json.loads(record_path.read_text())
    hive = record.get("hive") or {}
    lines = [f"Last run: {record.get('goal', '?')}",
             f"- record: {record_path}",
             f"- status: {record.get('status')} · Queen {record.get('queen', {}).get('name')} · "
             f"bees {record.get('workers', {}).get('name')} · cost ${hive.get('cost_usd') or 0:.2f}"]

    briefs = hive.get("briefs") or []
    labels = [b.get("label", "") for b in briefs]
    returned = sorted({label for label in labels if labels.count(label) > 1 and label[:1] in "BF"})
    lines.append(f"- briefs: {len(briefs)} · returned: {', '.join(returned) or 'none'}")
    for stage, data in sorted((hive.get("by_stage") or {}).items()):
        lines.append(f"  - {stage}: ≈${data.get('cost_usd_est') or 0:.3f}")

    failed_checks = [c["command"] for c in hive.get("checks") or [] if not c.get("ok")]
    lines.append(f"- failed checks by the Queen: {'; '.join(failed_checks) or 'none'}")
    for result in (record.get("acceptance") or {}).get("results") or []:
        lines.append(f"- acceptance {'passed' if result.get('ok') else 'FAILED'}: {result.get('command')}")

    events = record_path.with_name("events.jsonl")
    for line in events.read_text().splitlines() if events.exists() else []:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("kind") == "report" and event.get("ok") is False:
            lines.append(f"- failed report from {event.get('label')}: {event.get('text', '')[-300:].strip()}")

    review = (record.get("summary") or {}).get("review") or {}
    if review:
        lines.append(f"- review: lenses {', '.join(review.get('lenses') or []) or 'none'} · confirmed {review.get('confirmed', 0)} "
                     f"· fixed {review.get('fixed', 0)} · dismissed {review.get('dismissed', 0)}")
        lines += [f"  - open: {item}" for item in review.get("open") or []]
        lines += [f"  - suggestion: {item}" for item in review.get("suggestions") or []]
    return "\n".join(lines)


if __name__ == "__main__":
    found = last_run(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(facts(found) if found else "No recorded hive run for this project yet.")
