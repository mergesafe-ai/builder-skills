#!/usr/bin/env python3
"""Optional Claude Code hook: remind you to hand off when a session gets large.

Runs on UserPromptSubmit. It reads the real context size from the session
transcript and shows a one-line note, asking the agent to offer a handoff when
the task is done:
- once the context passes FIRST tokens (HANDOFF_HINT_FIRST, default 300000),
  then every STEP more;
- on a message sent IDLE_MIN or more minutes after the last reply, when the
  context is at least IDLE_FLOOR tokens. The prompt cache has likely expired
  by then, so this message re-writes the whole context: the cheapest moment
  to start fresh.
It never blocks a prompt and never fails one. Standard library only.

State is kept per session in ~/.claude/hook-state/.
"""
import json
import os
import sys
import time
from datetime import datetime


def _first() -> int:
    try:
        return int(os.environ.get("HANDOFF_HINT_FIRST", "300000"))
    except ValueError:
        return 300_000


FIRST, STEP = _first(), 100_000
IDLE_MIN, IDLE_FLOOR = 60, 80_000


def last_turn(path: str) -> tuple[int, str | None]:
    """Context size of the last assistant turn, and its timestamp."""
    size, at = 0, None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message")
                use = msg.get("usage") if rec.get("type") == "assistant" and isinstance(msg, dict) else None
                if use:
                    size = (use.get("input_tokens", 0) + use.get("cache_read_input_tokens", 0)
                            + use.get("cache_creation_input_tokens", 0) + use.get("output_tokens", 0))
                    at = rec.get("timestamp") or at
    except OSError:
        pass
    return size, at


def minutes_since(at: str | None) -> float | None:
    if not at:
        return None
    try:
        return (time.time() - datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()) / 60
    except ValueError:
        return None


def main() -> None:
    data = json.load(sys.stdin)
    size, at = last_turn(data.get("transcript_path") or "")
    if size < min(FIRST, IDLE_FLOOR):
        return
    state_path = os.path.expanduser(f"~/.claude/hook-state/handoff-{data.get('session_id') or 'unknown'}.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    try:
        state = json.load(open(state_path))
    except (OSError, ValueError):
        state = {}
    k = f"{size // 1000}k"
    notes = []
    idle = minutes_since(at)
    if idle is not None and idle >= IDLE_MIN and size >= IDLE_FLOOR:
        notes.append(f"Away {int(idle)} min on a {k}-token session: the cache has likely expired, so this "
                     "message re-sends all of it. If it's a new task, start fresh: /handoff, /clear, /handoff.")
    level = (size - FIRST) // STEP if size >= FIRST else -1
    if level >= 0 and level > state.get("level", -1):
        state["level"] = level
        json.dump(state, open(state_path, "w"))
        notes.append(f"This session's context is ~{k} tokens, re-read on every message. "
                     "When the current task is done: /handoff, then /clear, then /handoff.")
    if not notes:
        return
    print(json.dumps({
        "systemMessage": " ".join(notes),
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                f"[handoff hint] This session's context is ~{k} tokens and is re-read on every message. "
                "Answer the user's message as usual. Then, if the current task is done or at a natural "
                "break, follow the handoff skill: if no work is left, its 'When no work is left' section; "
                "otherwise its 'Write the handoff' steps, ending your reply with the line it specifies. If work is still mid-step, say what must "
                "finish first and write the handoff once it does."
            ),
        },
    }))


try:
    main()
except Exception:
    pass
