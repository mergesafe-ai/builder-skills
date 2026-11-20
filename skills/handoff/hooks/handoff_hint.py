#!/usr/bin/env python3
"""Optional Claude Code hook: remind you to hand off when a session gets large.

Runs on UserPromptSubmit. It reads the real context size from the session
transcript and, once it passes FIRST tokens (then every STEP more), shows a
one-line note and asks the agent to offer a handoff when the task is done.
It never blocks a prompt and never fails one. Standard library only.

State is kept per session in ~/.claude/hook-state/.
"""
import json
import os
import sys

FIRST, STEP = 150_000, 100_000


def context_size(path: str) -> int:
    size = 0
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
    except OSError:
        pass
    return size


def main() -> None:
    data = json.load(sys.stdin)
    size = context_size(data.get("transcript_path") or "")
    if size < FIRST:
        return
    state_path = os.path.expanduser(f"~/.claude/hook-state/handoff-{data.get('session_id') or 'unknown'}.json")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    try:
        state = json.load(open(state_path))
    except (OSError, ValueError):
        state = {}
    level = (size - FIRST) // STEP
    if level <= state.get("level", -1):
        return
    state["level"] = level
    json.dump(state, open(state_path, "w"))
    k = f"{size // 1000}k"
    print(json.dumps({
        "systemMessage": f"This session's context is ~{k} tokens, re-read on every message. "
                         "When the current task is done: /handoff, then /clear, then /handoff.",
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
