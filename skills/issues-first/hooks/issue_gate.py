#!/usr/bin/env python3
"""Optional Claude Code hook: no code changes until the work has an issue.

One script for two hook events:

- PreToolUse on Edit|Write|MultiEdit|NotebookEdit|Bash|Skill. An edit to a
  file in a git repo is blocked (exit 2) unless the branch names an issue
  (issue-12, 12-topic, #12), the session is bound to an issue, or the user
  exempted the session. On Bash only `git commit` and `git push` are judged.
  Loading issues-first or bug-to-issue with `pick-up <n>` binds the session.
- UserPromptSubmit. A typed `/issues-first pick-up <n>` or
  `/bug-to-issue pick-up <n>` binds the session; a typed
  `no-issue: <reason>` exempts it. Only the user types prompts, so the agent
  cannot exempt itself.

Files outside a git repo, and under issues/, .claude/ or handoffs/, are
always allowed. Every block, binding, exemption and error is appended to
~/.claude/skill-log.jsonl. If anything goes wrong the edit is allowed:
this hook never breaks a session. Standard library only.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import time

SKILLS = ("issues-first", "bug-to-issue")
FREE_DIRS = ("issues", ".claude", "handoffs")
EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}

PICK_UP = re.compile(r"(?:^|\s)/(?:issues-first|bug-to-issue)\s+pick-up\s+#?(\d+)\b")
PICK_UP_ARGS = re.compile(r"^\s*pick-up\s+#?(\d+)\b")
NO_ISSUE = re.compile(r"(?:^|\n)\s*no-issue:[ \t]*(\S[^\n]*)")
# issue-12 / issue12 / #12 anywhere, or a path segment that starts with 12-.
BRANCH_ISSUE = re.compile(r"(?:issue-?|#)(\d+)|(?:^|/)(\d+)-", re.I)

BLOCK = """Blocked by the issues-first gate: {where} has no issue for this work.
Every change starts from an issue. Either:
- file one with /issues-first (or /bug-to-issue for a bug), then pick it up with `pick-up <number>`;
- or ask the user to type `no-issue: <reason>` if this change really needs none.
Work on a branch that names the issue (issue-12-topic) and the gate stays out of the way."""


def claude_dir():
    return os.path.join(os.path.expanduser("~"), ".claude")


def log(event, data, **fields):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "skill": "issues-first",
             "event": event, "session": (data or {}).get("session_id"), **fields}
    try:
        os.makedirs(claude_dir(), exist_ok=True)
        with open(os.path.join(claude_dir(), "skill-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def state_path(data):
    session = re.sub(r"[^\w.-]", "_", data.get("session_id") or "unknown")
    return os.path.join(claude_dir(), "state", "issue-gate", session + ".json")


def load_state(data):
    try:
        with open(state_path(data), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(data, **changes):
    state = {**load_state(data), **changes}
    path = state_path(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def bind(data, issue, via):
    save_state(data, issue=issue)
    log("bind", data, issue=issue, via=via, repo=repo_name(data.get("cwd")))


def git(directory, *args):
    """Run git in directory; None when it fails (not a repo, no branch)."""
    r = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else None


def existing_dir(path):
    path = os.path.abspath(path)
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return path


def repo_name(cwd):
    try:
        root = cwd and git(cwd, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        root = None
    return os.path.basename(root) if root else None


def branch_issue(branch):
    m = BRANCH_ISSUE.search(branch or "")
    return int(next(g for g in m.groups() if g)) if m else None


def judge(data, directory, path, tool):
    """Exit 2 with a message when this change has no issue; return otherwise."""
    directory = existing_dir(directory)
    if not directory:
        return
    root = git(directory, "rev-parse", "--show-toplevel")
    if not root:
        return  # not a git repo
    if path:
        rel = os.path.relpath(os.path.realpath(os.path.abspath(path)), os.path.realpath(root))
        if rel.split(os.sep)[0] in FREE_DIRS:
            return
    branch = git(root, "symbolic-ref", "--short", "-q", "HEAD")
    if branch_issue(branch) is not None:
        return
    state = load_state(data)
    if state.get("issue") is not None or state.get("exempt"):
        return
    log("block", data, repo=os.path.basename(root), branch=branch, tool=tool, path=path or directory)
    where = f"branch `{branch}`" if branch else "this detached checkout"
    sys.stderr.write(BLOCK.format(where=where) + "\n")
    sys.exit(2)


VAR = re.compile(r"\$(\w+)|\$\{(\w+)\}")
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
SEPARATORS = {"&&", ";", "||", "|", "&", "(", ")"}


def resolve(path, variables, base):
    """`path` with ~ and assigned $VARs expanded, joined to base; None if a $ is left."""
    path = VAR.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), path)
    if "$" in path:
        return None
    return os.path.join(base, os.path.expanduser(path))


def git_targets(command, cwd):
    """Directories of every `git ... commit|push` in a shell command.

    Follows `cd <dir>` and `NAME=value` earlier in the line; no full shell parsing.
    """
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        words = command.split()
    targets, variables, here, i, start = [], {}, cwd, 0, True
    while i < len(words):
        word = words[i]
        if word in SEPARATORS:
            start, i = True, i + 1
        elif start and ASSIGN.match(word):
            name, _, value = word.partition("=")
            variables[name] = VAR.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), value)
            i += 1
        elif start and word == "cd" and i + 1 < len(words) and words[i + 1] not in SEPARATORS:
            here = resolve(words[i + 1], variables, here) or here
            i += 2
        elif os.path.basename(word) != "git":
            start, i = False, i + 1
        else:
            start = False
            directory, j = here, i + 1
            while j < len(words) and words[j].startswith("-"):
                if words[j] in ("-C", "-c") and j + 1 < len(words):
                    if words[j] == "-C":
                        directory = resolve(words[j + 1], variables, directory) or directory
                    j += 2
                else:
                    j += 1
            if j < len(words) and words[j] in ("commit", "push"):
                targets.append(directory)
            i = j
    return targets


def pre_tool_use(data):
    tool, args = data.get("tool_name"), data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Skill":
        name = (args.get("skill") or "").split(":")[-1]
        m = PICK_UP_ARGS.match(args.get("args") or "")
        if name in SKILLS and m:
            bind(data, int(m.group(1)), via="skill")
    elif tool in EDIT_TOOLS:
        path = args.get(EDIT_TOOLS[tool])
        if path:
            path = os.path.join(cwd, path)
            judge(data, os.path.dirname(path), path, tool)
    elif tool == "Bash":
        for directory in git_targets(args.get("command") or "", cwd):
            judge(data, directory, None, tool)


def user_prompt(data):
    text = data.get("prompt") or ""
    m = PICK_UP.search(text)
    if m:
        bind(data, int(m.group(1)), via="prompt")
    m = NO_ISSUE.search(text)
    if m:
        reason = m.group(1).strip()
        save_state(data, exempt=reason)
        log("exempt", data, reason=reason, repo=repo_name(data.get("cwd")))


def main():
    data = None
    try:
        data = json.load(sys.stdin)
        if data.get("hook_event_name") == "UserPromptSubmit":
            user_prompt(data)
        else:
            pre_tool_use(data)
    except SystemExit:
        raise
    except Exception as exc:  # never break a session
        log("error", data, error=f"{type(exc).__name__}: {exc}")
    sys.exit(0)


if __name__ == "__main__":
    main()
