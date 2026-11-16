#!/usr/bin/env python3
"""Estimate what handoffs would save you, from your own Claude Code session logs.

Standard library only. Reads the session logs Claude Code keeps on your machine
(~/.claude/projects/*/*.jsonl), and nothing leaves your computer.

It reports two things:
1. How much of your usage is the agent re-reading earlier conversation.
2. A replay estimate: the same sessions, but with a handoff to a fresh session
   every time the context passes a threshold.

Usage:
    python3 measure.py                      # all projects
    python3 measure.py ~/.claude/projects/<one-project-folder>
    python3 measure.py --at 150000 --restart 40000

This is an estimate, not a bill. Costs use list-price ratios between cache reads,
cache writes and output (0.1 : 1.25 or 2.0 : 5, relative to one input token). The
replay assumes a fresh session can continue the work after re-reading `--restart`
tokens. It does not know how your plan's usage limit is counted.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

READ, WRITE_5M, WRITE_1H, OUT = 0.1, 1.25, 2.0, 5.0
HANDOFF_OUTPUT_TOKENS = 1500


def load_sessions(root: str) -> list[list[tuple]]:
    paths = glob.glob(os.path.join(root, "*.jsonl")) + glob.glob(os.path.join(root, "*", "*.jsonl"))
    sessions = []
    for path in paths:
        calls = {}
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line or '"type":"assistant"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("isSidechain"):
                    continue
                msg = rec.get("message") or {}
                use = msg.get("usage")
                if not isinstance(use, dict):
                    continue
                split = use.get("cache_creation") or {}
                w5 = split.get("ephemeral_5m_input_tokens", 0) or 0
                w1 = split.get("ephemeral_1h_input_tokens", 0) or 0
                total_write = use.get("cache_creation_input_tokens", 0) or 0
                if w5 + w1 == 0:
                    w1 = total_write
                # A streamed reply is logged several times under one id: keep the last.
                calls[msg.get("id") or rec.get("uuid")] = (
                    rec.get("timestamp") or "",
                    use.get("input_tokens", 0) or 0,
                    use.get("cache_read_input_tokens", 0) or 0,
                    w5, w1,
                    use.get("output_tokens", 0) or 0,
                    msg.get("model") or "unknown",
                )
        if calls:
            sessions.append(sorted(calls.values()))
    return sessions


def replay(sessions, at: int, restart: int):
    """Return per-model totals: actual vs simulated, in cost units and raw tokens."""
    t = defaultdict(lambda: defaultdict(float))
    resets = 0
    for calls in sessions:
        prev = sim_ctx = base = None
        for _ts, inp, read, w5, w1, out, model in calls:
            ctx = inp + read + w5 + w1
            m = t[model]
            m["calls"] += 1
            m["cost"] += inp + READ * read + WRITE_5M * w5 + WRITE_1H * w1 + OUT * out
            m["tokens"] += ctx + out
            m["reread_cost"] += READ * read
            m["reread_tokens"] += read
            if base is None:
                base, sim_ctx = ctx + restart, ctx
            else:
                grew = ctx - prev
                # If the real session shrank (it was compacted), the replay cannot be larger.
                sim_ctx = sim_ctx + grew if grew >= 0 else min(sim_ctx, ctx)
            prev = ctx
            if sim_ctx >= at:
                resets += 1
                sim_ctx = base
                m["sim_cost"] += WRITE_1H * base + OUT * HANDOFF_OUTPUT_TOKENS
                m["sim_tokens"] += base + HANDOFF_OUTPUT_TOKENS
            keep = min(1.0, sim_ctx / ctx) if ctx else 1.0
            m["sim_cost"] += inp + READ * read * keep + WRITE_5M * w5 + WRITE_1H * w1 + OUT * out
            m["sim_tokens"] += inp + read * keep + w5 + w1 + out
    return t, resets


def pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "   n/a"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--at", type=int, default=150_000, help="hand off when context passes this many tokens")
    ap.add_argument("--restart", type=int, default=40_000, help="tokens a fresh session re-reads to catch up")
    args = ap.parse_args()

    sessions = load_sessions(os.path.expanduser(args.root))
    if not sessions:
        print(f"No Claude Code session logs found under {args.root}")
        return
    totals, resets = replay(sessions, args.at, args.restart)
    calls = sum(m["calls"] for m in totals.values())
    print(f"Sessions: {len(sessions)}   model calls: {int(calls)}   simulated handoffs: {resets}")
    print(f"Handoff at {args.at:,} tokens of context, {args.restart:,} tokens to restart\n")
    print(f"{'model':28s} {'calls':>7s}  {'re-read share':>14s}  {'est. saving':>12s}  {'(raw tokens)':>12s}")
    all_ = defaultdict(float)
    for model, m in sorted(totals.items(), key=lambda kv: -kv[1]["cost"]):
        for k, v in m.items():
            all_[k] += v
        if m["calls"] < 50:
            continue
        print(f"{model:28s} {int(m['calls']):7d}  {pct(m['reread_cost'], m['cost']):>14s}  "
              f"{pct(m['cost'] - m['sim_cost'], m['cost']):>12s}  {pct(m['tokens'] - m['sim_tokens'], m['tokens']):>12s}")
    print(f"{'all models':28s} {int(all_['calls']):7d}  {pct(all_['reread_cost'], all_['cost']):>14s}  "
          f"{pct(all_['cost'] - all_['sim_cost'], all_['cost']):>12s}  {pct(all_['tokens'] - all_['sim_tokens'], all_['tokens']):>12s}")
    print("\nRe-read share and est. saving are cost-weighted. An estimate from a replay, not a bill.")


if __name__ == "__main__":
    main()
