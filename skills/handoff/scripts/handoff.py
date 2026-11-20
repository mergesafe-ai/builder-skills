#!/usr/bin/env python3
"""Name a new handoff, or find one by its short id. Run from the project root.

    python3 handoff.py new <topic>   # prints handoffs/<id>-<topic>.md (a free 6-character id)
    python3 handoff.py find [id]     # prints the handoff with that id, or the newest one

`find` forgives what a pasted id picks up: `#ec84ca.`, `ec84ca,` and ` EC84CA `
all mean ec84ca. With no exact match, it loads a handoff saved in the last
RECENT_H hours whose id is one character off or starts with what was typed, if
exactly one does, and says so. If several do, it lists them and loads none.
Exit code 0 when a handoff was printed, 1 when not. Standard library only.

Handoffs go in ./handoffs/ unless HANDOFF_DIR is set, e.g.
HANDOFF_DIR='~/.claude/handoffs/{repo}' keeps them out of the repo; {repo} is
the main checkout's folder name, so every worktree of a repo shares one folder.
"""
import os
import re
import secrets
import subprocess
import sys
import time

RECENT_H = 24
ID = re.compile(r"^([0-9a-f]{6})(?:-|\.md$)")


def repo_name():
    """The main checkout's folder name (the same from any worktree), else the cwd's."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ""
    root = os.path.dirname(common) if common.endswith(os.sep + ".git") else os.getcwd()
    return os.path.basename(root) or "project"


def folder():
    custom = os.environ.get("HANDOFF_DIR", "").strip()
    if not custom:
        return "handoffs"
    return os.path.expanduser(custom.replace("{repo}", repo_name()))


def handoffs():
    try:
        names = os.listdir(folder())
    except OSError:
        return []
    paths = [os.path.join(folder(), n) for n in names if n.endswith(".md")]
    return sorted(paths, key=os.path.getmtime, reverse=True)


def id_of(path):
    m = ID.match(os.path.basename(path))
    return m.group(1) if m else None


def clean(typed):
    runs = re.findall(r"[0-9a-f]+", typed.lower())
    return max(runs, key=len) if runs else ""


def one_off(a, b):
    """True when a and b differ by one changed, added or dropped character."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:] if len(a) < len(b) else a[i + 1:] == b[i:]


def age(path):
    hours = (time.time() - os.path.getmtime(path)) / 3600
    return f"{int(hours * 60)} min ago" if hours < 1 else f"{int(hours)}h ago"


def show(path, note=""):
    hid = id_of(path)
    print(f"Handoff {hid + ' ' if hid else ''}({path}, saved {age(path)}):")
    if note:
        print(note)
    print()
    print(open(path, encoding="utf-8").read())


def find(typed):
    paths = handoffs()
    if not typed.strip():
        if not paths:
            print(f"NO HANDOFF FOUND: {folder()}/ is empty or missing.")
            return 1
        show(paths[0])
        return 0
    want = clean(typed)
    exact = [p for p in paths if id_of(p) == want]
    if exact:
        show(exact[0])
        return 0
    cutoff = time.time() - RECENT_H * 3600
    near = [p for p in paths if id_of(p) and os.path.getmtime(p) >= cutoff
            and (one_off(want, id_of(p)) or (len(want) >= 3 and id_of(p).startswith(want)))]
    if len(near) == 1:
        show(near[0], f"No {want}; loaded {id_of(near[0])} (saved {age(near[0])}), the only close match.")
        return 0
    if near:
        print(f"NO HANDOFF LOADED: no {want}, and several recent ones are close. Run /handoff <id> with one of:")
        for p in near:
            print(f"- {id_of(p)}  {p}  saved {age(p)}")
        return 1
    print(f"NO HANDOFF FOUND for {want or typed.strip()!r} in {folder()}/.")
    return 1


def new(topic):
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40].strip("-") or "handoff"
    taken = {id_of(p) for p in handoffs()}
    hid = secrets.token_hex(3)
    while hid in taken:
        hid = secrets.token_hex(3)
    print(f"{folder()}/{hid}-{slug}.md")
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "new":
        return new(" ".join(argv[2:]))
    if len(argv) >= 2 and argv[1] == "find":
        return find(" ".join(argv[2:]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
