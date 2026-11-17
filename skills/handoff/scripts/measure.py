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

This is an estimate, not a bill. Costs use each model's list prices (PRICES below):
cache reads are 0.1x the input price on most models but 0.05x on Opus 5.5 and
Sonnet 5.5 and 0.025x on Fable/Mythos 5.1 and 5.2, so the same handoff saves less
on those. Cache writes are 1.25x (5-minute) or 2x (1-hour), output 5x. The
replay assumes a fresh session can continue the work after re-reading `--restart`
tokens. It does not know how your plan's usage limit is counted.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

WRITE_5M, WRITE_1H, OUT = 1.25, 2.0, 5.0
HANDOFF_OUTPUT_TOKENS = 1500

# (model-id prefix, input $ per million tokens, cache-read multiple of input).
# First match wins, so longer prefixes come first. Anthropic list prices, 2026-11.
PRICES = [
    ("claude-fable-5-2", 8.0, 0.025), ("claude-mythos-5-2", 8.0, 0.025),
    ("claude-fable-5-1", 10.0, 0.025), ("claude-mythos-5-1", 10.0, 0.025),
    ("claude-fable-5", 10.0, 0.1), ("claude-mythos-5", 10.0, 0.1),
    ("claude-opus-5-5", 4.0, 0.05), ("claude-opus-5", 5.0, 0.1), ("claude-opus-4", 5.0, 0.1),
    ("claude-sonnet-5-5", 2.0, 0.05), ("claude-sonnet-5", 2.0, 0.1), ("claude-sonnet-4", 3.0, 0.1),
    ("claude-haiku-5-5", 0.1, 0.1), ("claude-haiku-4", 1.0, 0.1),
]
HAIKU_LONG = 100_000  # Haiku 5.5 charges 5x per token once the prompt passes this


def price(model: str, ctx: int) -> tuple[float, float]:
    """Return ($ per input-token-equivalent, cache-read multiple) for one call."""
    for prefix, usd, read in PRICES:
        if model.startswith(prefix):
            if prefix == "claude-haiku-5-5" and ctx > HAIKU_LONG:
                usd *= 5
            return usd / 1e6, read
    return 3.0 / 1e6, 0.1  # unknown model: a mid-range guess at the usual ratios


def cost(usd: float, read_x: float, inp, read, w5, w1, out) -> float:
    return usd * (inp + read_x * read + WRITE_5M * w5 + WRITE_1H * w1 + OUT * out)


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
    """Return per-model totals: actual vs simulated, in list-price dollars and raw tokens."""
    t = defaultdict(lambda: defaultdict(float))
    resets = 0
    for calls in sessions:
        prev = sim_ctx = base = None
        for _ts, inp, read, w5, w1, out, model in calls:
            ctx = inp + read + w5 + w1
            m = t[model]
            usd, read_x = price(model, ctx)
            m["calls"] += 1
            m["cost"] += cost(usd, read_x, inp, read, w5, w1, out)
            m["tokens"] += ctx + out
            m["reread_cost"] += usd * read_x * read
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
                b_usd, _ = price(model, base)
                m["sim_cost"] += cost(b_usd, 0, 0, 0, 0, base, HANDOFF_OUTPUT_TOKENS)
                m["sim_tokens"] += base + HANDOFF_OUTPUT_TOKENS
            keep = min(1.0, sim_ctx / ctx) if ctx else 1.0
            s_usd, _ = price(model, sim_ctx)
            m["sim_cost"] += cost(s_usd, read_x, inp, read * keep, w5, w1, out)
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
    print(f"{'model':28s} {'calls':>7s}  {'re-read share':>14s}  {'est. saving':>12s}  "
          f"{'(raw tokens)':>12s}  {'list-price $ now -> with handoffs':>34s}")

    def row(name: str, m) -> None:
        dollars = f"{m['cost']:,.2f} -> {m['sim_cost']:,.2f}"
        print(f"{name:28s} {int(m['calls']):7d}  {pct(m['reread_cost'], m['cost']):>14s}  "
              f"{pct(m['cost'] - m['sim_cost'], m['cost']):>12s}  "
              f"{pct(m['tokens'] - m['sim_tokens'], m['tokens']):>12s}  {dollars:>34s}")

    all_ = defaultdict(float)
    for model, m in sorted(totals.items(), key=lambda kv: -kv[1]["cost"]):
        for k, v in m.items():
            all_[k] += v
        if m["calls"] >= 50 and m["cost"]:
            row(model, m)
    row("all models", all_)
    print("\nRe-read share and est. saving are weighted by each model's list prices.")
    print("An estimate from a replay, not a bill: subscription plans don't publish how they count usage.")


if __name__ == "__main__":
    main()
