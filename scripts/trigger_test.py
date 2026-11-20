#!/usr/bin/env python3
"""Which skill does Claude Code load for each prompt?

Runs Claude Code headless from inside a scratch fixture project (never this
repo), several times per prompt, and prints a Markdown table of the skill
each run loaded first. A run that edits or runs commands before loading any
skill is marked "acted".

Usage:
    python3 scripts/trigger_test.py <fixture-dir> <prompts.tsv> [--runs 3] [--model sonnet]

The fixture is a small git project you made for the test. This script copies
every folder under skills/ into <fixture>/.claude/skills/ first. The prompts
file has one tab-separated line per prompt: id, expected skill (or "none"),
kind ("user" or "agent"), prompt. Agent prompts get more turns, so the agent
has room to decide on its own to act.

The runs can only read files and load skills: editing and shell commands are
denied, and user-level settings, skills and MCP servers are not loaded.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

ACTIONS = {"Bash", "Edit", "Write", "NotebookEdit", "Agent", "Task"}


def run(fixture, prompt, turns, model, out):
    cmd = [
        "claude", "-p", prompt, "--model", model,
        "--output-format", "stream-json", "--verbose", "--max-turns", str(turns),
        "--setting-sources", "project", "--strict-mcp-config",
        "--permission-mode", "dontAsk", "--allowedTools", "Read Glob Grep Skill",
        "--no-session-persistence",
    ]
    with open(out, "w") as f:
        subprocess.run(cmd, cwd=fixture, stdout=f, stderr=subprocess.STDOUT, timeout=600)


def first_skill(out):
    skill, acted = None, set()
    for line in open(out):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event["message"]["content"]:
            if block.get("type") != "tool_use" or skill:
                continue
            if block["name"] == "Skill":
                skill = block["input"].get("skill")
            elif block["name"] in ACTIONS:
                acted.add(block["name"])
    cell = skill or "none"
    if acted:
        cell += (" (after " if skill else " (acted: ") + ",".join(sorted(acted)) + ")"
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("prompts")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = os.path.abspath(args.fixture)
    if os.path.commonpath([fixture, repo]) == repo:
        raise SystemExit("Put the fixture outside this repo.")
    target = os.path.join(fixture, ".claude", "skills")
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(os.path.join(repo, "skills")):
        shutil.rmtree(os.path.join(target, name), ignore_errors=True)
        shutil.copytree(os.path.join(repo, "skills", name), os.path.join(target, name))

    rows = [line.split("\t") for line in open(args.prompts).read().splitlines() if line.strip()]
    outdir = tempfile.mkdtemp(prefix="trigger-test-")
    jobs = []
    for pid, _, kind, prompt in rows:
        turns = 5 if kind == "agent" else 3
        for r in range(args.runs):
            jobs.append((fixture, prompt, turns, args.model, f"{outdir}/{pid}.{r}.json"))
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda j: run(*j), jobs))

    print("| id | expected | prompt | " + " | ".join(f"run {r + 1}" for r in range(args.runs)) + " |")
    print("|---" * (3 + args.runs) + "|")
    for pid, expected, _, prompt in rows:
        cells = [first_skill(f"{outdir}/{pid}.{r}.json") for r in range(args.runs)]
        print(f"| {pid} | {expected} | {prompt} | " + " | ".join(cells) + " |")
    print(f"\nRaw streams: {outdir}")


if __name__ == "__main__":
    main()
