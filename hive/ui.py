"""Small terminal helpers: menus and confirmations that degrade gracefully without a TTY."""

import asyncio
import sys

_prompt_lock = asyncio.Lock()


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def choose(title: str, options: list[tuple[str, str, bool]], default: str | None = None) -> str:
    """Numbered menu. options = [(key, label, enabled)]. Enter picks the default."""
    enabled = [key for key, _, ok in options if ok]
    if not enabled:
        raise SystemExit(f"{title}: nothing available to choose.")
    if default not in enabled:
        default = enabled[0]
    if not interactive():
        return default

    print(title)
    numbered: dict[str, str] = {}
    n = 0
    for key, label, ok in options:
        if ok:
            n += 1
            numbered[str(n)] = key
            marker = "❯" if key == default else " "
            print(f"  {marker} {n}) {label}")
        else:
            print(f"    ✗  {label}")
    while True:
        answer = input(f"Choose 1-{n} [Enter = {default}]: ").strip().lower()
        if not answer:
            return default
        if answer in numbered:
            return numbered[answer]
        if answer in enabled:
            return answer
        print("  Please type a number from the list.")


def confirm(question: str, default: bool = True) -> bool:
    if not interactive():
        return default
    hint = "Y/n" if default else "y/N"
    answer = input(f"{question} [{hint}]: ").strip().lower()
    return default if not answer else answer in ("y", "yes", "д", "да")


async def ask_async(question: str) -> str:
    """input() from async code, one question at a time even when bees run in parallel."""
    async with _prompt_lock:
        return await asyncio.to_thread(input, question)
