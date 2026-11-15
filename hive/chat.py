"""`hive chat`: an ongoing conversation with the Queen, plus `hive waggle` built on top of it."""

import asyncio
import time
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

from hive import memory, models, stats, verify
from hive.folders import start_point
from hive.models import choose_queen
from hive.modes import MODES, Policy, choose_mode
from hive.render import EventLog, Tracker
from hive.session import Job, build_options, build_record, converse, new_run_dir, plugin_for, queen_prompt

HELP = """commands:
  /mode [plan|auto|ask]   change the autonomy mode
  /queen [model]          change the Queen (the conversation continues)
  /dirs PATH              grant access to another folder
  /cost                   cost of this chat so far
  /waggle  or  /retro     session retro with proposed rule and memory edits
  /help                   this help
  /exit                   leave (Ctrl-D works too)
anything else is a goal or a follow-up for the Queen."""

CHAT_NOTE = ("\n# Chat\nThis is an interactive chat. The user sends several goals and follow-ups. "
             "Run the full workflow (briefs, verification, review, memory, hive-summary block) for each goal that "
             "changes something. For plain questions, just answer.")


class ChatSession:
    def __init__(self, job: Job):
        self.job = job
        self.pdir = memory.ensure_project(job.folders[0])
        self.session_id: str | None = None
        self.client: ClaudeSDKClient | None = None
        self.policy: Policy | None = None
        self.total_cost = 0.0
        self.start = None

    async def connect(self) -> None:
        if self.client:
            await self.client.disconnect()
        self.policy = Policy(self.job.mode, [*self.job.folders, self.pdir], memory.commands(self.pdir))
        options = build_options(self.job, self.policy, self.pdir,
                                queen_prompt(self.job, self.pdir, self.start) + CHAT_NOTE, plugin_for(self.job.workers))
        options.resume = self.session_id
        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()

    async def turn(self, prompt: str) -> None:
        run_dir = new_run_dir(self.pdir)
        log = EventLog(run_dir / "events.jsonl")
        started = time.time()
        log.emit("run_start", goal=prompt, queen=self.job.queen.key, workers=self.job.workers.key, mode=self.job.mode,
                 folders=[str(f) for f in self.job.folders], project_dir=str(self.pdir), review=self.job.review, chat=True)
        tracker = Tracker(log=log, verbose=self.job.verbose)
        await converse(self.client, prompt, tracker)
        if tracker.result:
            self.session_id = tracker.result.session_id
            self.total_cost += tracker.result.total_cost_usd or 0

        summary = verify.parse_summary(tracker.last_queen_text)
        if summary is None:   # a plain answer, not a job
            return
        cmds = verify.acceptance_commands([], summary, memory.commands(self.pdir))
        results = verify.run_checks(cmds, self.job.folders[0]) if cmds else []
        record = build_record(Job(**{**self.job.__dict__, "goal": prompt}), self.pdir, run_dir, started, self.start,
                              tracker, cmds, results, [], summary)
        stats.save(record, run_dir)
        log.emit("run_end", status=record["status"], cost_usd=record["hive"]["cost_usd"],
                 passed=record["acceptance"]["passed"], record=record["path"])
        stats.print_report(record)

    async def command(self, line: str) -> bool:
        """Handle a /command. Returns False to leave the chat."""
        name, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        if name in ("exit", "quit", "q"):
            return False
        if name == "help":
            print(HELP)
        elif name == "mode":
            mode = arg or choose_mode(self.job.mode)
            if mode not in MODES:
                print(f"unknown mode '{mode}'. Use one of: {', '.join(MODES)}")
            else:
                self.job.mode = mode
                await self.connect()
                print(f"mode: {mode}")
        elif name == "queen":
            self.job.queen = models.get(arg) if arg else choose_queen(self.job.queen.key)
            await self.connect()
            print(f"👑 Queen: {self.job.queen.name}")
        elif name == "dirs":
            folder = Path(arg).expanduser().resolve()
            if not folder.is_dir():
                print(f"not a folder: {folder}")
            else:
                self.job.folders.append(folder)
                await self.connect()
                print(f"📂 access granted: {folder}")
        elif name == "cost":
            print(f"this chat so far: ${self.total_cost:.3f}")
        elif name in ("waggle", "retro"):
            await self.turn("/haiku-hive:waggle " + arg)
        else:
            print(f"unknown command /{name}. Type /help.")
        return True


async def chat(job: Job, first_prompt: str | None = None) -> None:
    session = ChatSession(job)
    run_dir = new_run_dir(session.pdir)
    session.start = start_point(job.folders[0], run_dir)
    for folder in job.folders:
        print(f"📂 access granted: {folder}")
    print(f"👑 Queen: {job.queen.name} · 🐝 bees: {job.workers.name} · mode: {job.mode}. Type /help for commands.")
    await session.connect()
    try:
        if first_prompt:
            await session.turn(first_prompt)
        while True:
            try:
                line = (await asyncio.to_thread(input, "\n🐝> ")).strip()
            except EOFError:
                break
            if not line:
                continue
            if line.startswith("/"):
                if not await session.command(line):
                    break
            else:
                await session.turn(line)
    finally:
        if session.client:
            await session.client.disconnect()
        print(f"bye · this chat cost ${session.total_cost:.3f}")
