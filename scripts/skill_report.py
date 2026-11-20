#!/usr/bin/env python3
"""Where do the skills get in the way? Summarize ~/.claude/skill-log.jsonl.

The issues-first gate hook writes one line per block, binding, exemption and
error. This prints, for the last N days: blocks per repo, every exemption
with its reason, how sessions got bound to an issue, how many sessions were
blocked before they picked an issue up, and any hook errors. Each block or
exemption that shouldn't have happened is a skill to fix.

Usage:
    python3 scripts/skill_report.py [--days 7] [--log ~/.claude/skill-log.jsonl]
"""
import argparse
import json
import os
import time
from collections import Counter


def read(path, since):
    entries = []
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("ts", "") >= since:
                    entries.append(entry)
    except OSError:
        pass
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--log", default="~/.claude/skill-log.jsonl")
    opts = ap.parse_args()
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - opts.days * 86400))
    entries = read(opts.log, since)
    if not entries:
        print(f"Nothing logged in the last {opts.days} days ({opts.log}).")
        return
    by = {kind: [e for e in entries if e.get("event") == kind] for kind in ("block", "bind", "exempt", "error")}

    print(f"Last {opts.days} days: {len(by['block'])} blocks, {len(by['bind'])} bindings, "
          f"{len(by['exempt'])} exemptions, {len(by['error'])} errors.\n")

    if by["block"]:
        print("Blocks per repo:")
        for repo, n in Counter(e.get("repo") or "?" for e in by["block"]).most_common():
            print(f"  {n:4}  {repo}")
        bound = {e.get("session") for e in by["bind"]}
        blocked = {e.get("session") for e in by["block"]}
        print(f"\nSessions blocked: {len(blocked)}; of these, later picked up an issue: {len(blocked & bound)}.\n")

    if by["exempt"]:
        print("Exemptions (no-issue):")
        for e in by["exempt"]:
            print(f"  {e.get('ts', '')[:10]}  {e.get('repo') or '?'}: {e.get('reason')}")
        print()

    if by["bind"]:
        via = Counter(e.get("via") or "?" for e in by["bind"])
        print("Bindings: " + ", ".join(f"{n} via {k}" for k, n in via.most_common()) + "\n")

    if by["error"]:
        print("Hook errors (the edit was allowed):")
        for msg, n in Counter(e.get("error") for e in by["error"]).most_common(10):
            print(f"  {n:4}  {msg}")


if __name__ == "__main__":
    main()
