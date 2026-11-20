"""Tests for skills/issues-first/hooks/issue_gate.py.

Each test runs the hook as Claude Code would: JSON on stdin, HOME pointed at
a temporary folder so state and the log never touch the real ~/.claude.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "skills" / "issues-first" / "hooks" / "issue_gate.py"


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return {**os.environ, "HOME": str(home)}


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "proj"
    path.mkdir()
    git = ["git", "-C", str(path)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    (path / "app.py").write_text("x = 1\n")
    return path


def hook(env, payload, session="s1"):
    payload = {"session_id": session, **payload}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True)


def edit(env, path, session="s1", tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return hook(env, {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(Path(path).parent),
                      "tool_input": {key: str(path)}}, session)


def prompt(env, text, session="s1"):
    return hook(env, {"hook_event_name": "UserPromptSubmit", "prompt": text}, session)


def bash(env, command, cwd, session="s1"):
    return hook(env, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
                      "tool_input": {"command": command}}, session)


def log(env):
    path = Path(env["HOME"]) / ".claude" / "skill-log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def branch(repo, name):
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", name], check=True)


# --- blocked ---------------------------------------------------------------

@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_edit_on_main_without_issue_is_blocked_and_logged(env, repo, tool):
    r = edit(env, repo / "app.py", tool=tool)
    assert r.returncode == 2
    assert "/issues-first" in r.stderr and "no-issue:" in r.stderr
    [entry] = log(env)
    assert entry["event"] == "block" and entry["tool"] == tool
    assert entry["repo"] == repo.name and entry["path"].endswith("app.py") and entry["session"] == "s1"


def test_new_file_in_missing_folder_is_judged_by_its_repo(env, repo):
    assert edit(env, repo / "new" / "deep" / "mod.py", tool="Write").returncode == 2


def test_detached_head_without_binding_is_blocked(env, repo):
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "--detach"], check=True)
    assert edit(env, repo / "app.py").returncode == 2


@pytest.mark.parametrize("command", [
    "git commit -m wip",
    "git add -A && git commit -am wip",
    "git push origin main",
])
def test_git_commit_and_push_are_blocked(env, repo, command):
    r = bash(env, command, repo)
    assert r.returncode == 2
    assert log(env)[0]["tool"] == "Bash"


def test_git_dash_c_is_judged_by_that_directory(env, repo, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert bash(env, f"git -C {repo} commit -m x", plain).returncode == 2
    branch(repo, "issue-4-x")
    blocked_here = tmp_path / "other"
    blocked_here.mkdir()
    subprocess.run(["git", "-C", str(blocked_here), "init", "-q", "-b", "main"], check=True)
    assert bash(env, f"git -C {repo} commit -m x", blocked_here).returncode == 0


# --- allowed ---------------------------------------------------------------

def test_file_outside_any_repo_is_allowed(env, tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    assert edit(env, loose / "notes.txt", tool="Write").returncode == 0
    assert log(env) == []


@pytest.mark.parametrize("sub", ["issues/3-topic.md", ".claude/settings.json", "handoffs/abc123.md"])
def test_issue_and_tooling_folders_are_allowed(env, repo, sub):
    assert edit(env, repo / sub, tool="Write").returncode == 0


@pytest.mark.parametrize("name", ["issue-12", "12-topic", "fix/#12", "agent/issue-41-retry", "feat/12-x"])
def test_branch_naming_an_issue_is_allowed(env, repo, name):
    branch(repo, name)
    assert edit(env, repo / "app.py").returncode == 0
    assert bash(env, "git commit -m x", repo).returncode == 0


@pytest.mark.parametrize("name", ["release-2026-11", "v2-cleanup", "issues-first-fix"])
def test_branch_with_stray_digits_is_not_an_issue(env, repo, name):
    branch(repo, name)
    assert edit(env, repo / "app.py").returncode == 2


def test_other_shell_commands_are_allowed(env, repo):
    assert bash(env, "ls && git status && echo 'git commit'x", repo).returncode == 0
    assert bash(env, "git log --oneline", repo).returncode == 0


@pytest.mark.parametrize("text", ["/issues-first pick-up 12", "please /bug-to-issue pick-up #12 now"])
def test_typed_pick_up_binds_the_session(env, repo, text):
    assert prompt(env, text).returncode == 0
    assert edit(env, repo / "app.py").returncode == 0
    assert edit(env, repo / "app.py", session="other").returncode == 2
    bind = [e for e in log(env) if e["event"] == "bind"]
    assert bind and bind[0]["issue"] == 12


@pytest.mark.parametrize("skill", ["issues-first", "bug-to-issue", "builder:issues-first"])
def test_agent_loading_skill_with_pick_up_binds_the_session(env, repo, skill):
    r = hook(env, {"hook_event_name": "PreToolUse", "tool_name": "Skill", "cwd": str(repo),
                   "tool_input": {"skill": skill, "args": "pick-up 7"}})
    assert r.returncode == 0
    assert edit(env, repo / "app.py").returncode == 0
    assert [e["issue"] for e in log(env) if e["event"] == "bind"] == [7]


def test_skill_without_pick_up_does_not_bind(env, repo):
    hook(env, {"hook_event_name": "PreToolUse", "tool_name": "Skill", "cwd": str(repo),
               "tool_input": {"skill": "issues-first", "args": "new"}})
    hook(env, {"hook_event_name": "PreToolUse", "tool_name": "Skill", "cwd": str(repo),
               "tool_input": {"skill": "handoff", "args": "pick-up 7"}})
    assert edit(env, repo / "app.py").returncode == 2


def test_typed_no_issue_exempts_the_session_with_its_reason(env, repo):
    assert prompt(env, "no-issue: fixing a typo in the docs").returncode == 0
    assert edit(env, repo / "app.py").returncode == 0
    [entry] = [e for e in log(env) if e["event"] == "exempt"]
    assert entry["reason"] == "fixing a typo in the docs"


def test_no_issue_without_a_reason_does_not_exempt(env, repo):
    prompt(env, "no-issue:")
    assert edit(env, repo / "app.py").returncode == 2


# --- never break a session -------------------------------------------------

def test_unreadable_input_is_allowed_and_logged(env):
    r = subprocess.run([sys.executable, str(HOOK)], input="not json", env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert log(env)[0]["event"] == "error"


def test_missing_git_is_allowed_and_logged(env, repo):
    r = edit({**env, "PATH": "/nonexistent"}, repo / "app.py")
    assert r.returncode == 0
    assert log(env)[0]["event"] == "error"
