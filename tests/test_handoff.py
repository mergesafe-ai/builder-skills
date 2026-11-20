"""Tests for skills/handoff/scripts/handoff.py: short ids and finding a handoff by id."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "handoff" / "scripts" / "handoff.py"


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "handoffs").mkdir()
    return tmp_path


def save(proj, name, body="", age_h=1.0):
    path = proj / "handoffs" / name
    path.write_text(body or f"# Handoff: {name}\n")
    t = time.time() - age_h * 3600
    os.utime(path, (t, t))
    return path


def run(proj, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=proj, capture_output=True, text=True)


@pytest.mark.parametrize("typed", ["ec84ca", "ec84ca.", "#ec84ca", " EC84CA ", "ec84ca,"])
def test_find_cleans_the_id(proj, typed):
    save(proj, "ec84ca-search-cache.md", "BODY-A")
    save(proj, "1b2c3d-other.md", "BODY-B")
    out = run(proj, "find", typed)
    assert out.returncode == 0, out.stdout
    assert "BODY-A" in out.stdout and "BODY-B" not in out.stdout
    assert "no handoff" not in out.stdout.lower()


@pytest.mark.parametrize("typed", ["ec84cb", "ec84c", "ec84caa", "ec84"])
def test_find_loads_a_unique_near_match_and_says_so(proj, typed):
    save(proj, "ec84ca-search-cache.md", "BODY-A")
    save(proj, "1b2c3d-other.md", "BODY-B")
    out = run(proj, "find", typed)
    assert out.returncode == 0, out.stdout
    assert "BODY-A" in out.stdout and "BODY-B" not in out.stdout
    assert f"no {typed}" in out.stdout.lower() and "loaded ec84ca" in out.stdout.lower()


def test_ambiguous_id_lists_candidates_and_loads_none(proj):
    save(proj, "ec84ca-one.md", "BODY-A")
    save(proj, "ec84cc-two.md", "BODY-C")
    out = run(proj, "find", "ec84cb")
    assert out.returncode == 1
    assert "ec84ca" in out.stdout and "ec84cc" in out.stdout
    assert "BODY-A" not in out.stdout and "BODY-C" not in out.stdout


def test_near_match_only_among_recent_handoffs(proj):
    save(proj, "ec84ca-old.md", "BODY-A", age_h=48)
    out = run(proj, "find", "ec84cb")
    assert out.returncode == 1 and "BODY-A" not in out.stdout
    assert run(proj, "find", "ec84ca").returncode == 0  # an exact id loads at any age


def test_find_without_id_loads_the_newest(proj):
    save(proj, "aaaaaa-older.md", "OLDER", age_h=5)
    save(proj, "2026-11-01-dated.md", "DATED", age_h=3)
    save(proj, "bbbbbb-newer.md", "NEWER", age_h=1)
    out = run(proj, "find")
    assert out.returncode == 0 and "NEWER" in out.stdout and "OLDER" not in out.stdout


def test_find_with_no_handoffs(proj):
    out = run(proj, "find")
    assert out.returncode == 1 and "no handoff" in out.stdout.lower()


def test_new_gives_a_fresh_short_id(proj):
    save(proj, "ec84ca-x.md")
    out = run(proj, "new", "Search cache: phase 2!")
    assert out.returncode == 0
    path = out.stdout.strip()
    assert re.fullmatch(r"handoffs/[0-9a-f]{6}-search-cache-phase-2\.md", path), path
    assert not path.startswith("handoffs/ec84ca")
    assert not (proj / path).exists()  # it names the file; the agent writes it


def test_handoff_dir_is_shared_by_worktrees_and_loads_bare_ids(tmp_path):
    main = tmp_path / "myrepo"
    main.mkdir()
    git = lambda *a, cwd=main: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    git("worktree", "add", "-q", str(tmp_path / "wt-topic"))
    store = tmp_path / "store"
    (store / "myrepo").mkdir(parents=True)
    (store / "myrepo" / "3b6385.md").write_text("BARE")
    env = {**os.environ, "HANDOFF_DIR": str(store / "{repo}")}
    for cwd in (main, tmp_path / "wt-topic"):
        out = subprocess.run([sys.executable, str(SCRIPT), "find", "3b6385"], cwd=cwd, env=env,
                             capture_output=True, text=True)
        assert out.returncode == 0 and "BARE" in out.stdout, out.stdout
        new = subprocess.run([sys.executable, str(SCRIPT), "new", "x"], cwd=cwd, env=env,
                             capture_output=True, text=True).stdout.strip()
        assert new.startswith(str(store / "myrepo") + "/"), new
    assert not (main / "handoffs").exists()


HINT = SCRIPT.parents[1] / "hooks" / "handoff_hint.py"


@pytest.mark.parametrize("size,ago_min,expect", [
    (90_000, 120, "Away"),       # big enough, cache expired
    (90_000, 5, None),           # cache still warm
    (50_000, 120, None),         # too small to matter
    (160_000, 5, "context is"),  # size threshold alone
])
def test_hint_warns_after_the_cache_expires(tmp_path, monkeypatch, size, ago_min, expect):
    monkeypatch.setenv("HOME", str(tmp_path))
    at = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - ago_min * 60))
    tr = tmp_path / "t.jsonl"
    tr.write_text('{"type":"assistant","timestamp":"%s","message":{"usage":{"input_tokens":%d}}}\n' % (at, size))
    payload = '{"transcript_path":"%s","session_id":"s1"}' % tr
    out = subprocess.run([sys.executable, str(HINT)], input=payload, capture_output=True, text=True).stdout
    if expect:
        assert expect in out
    else:
        assert out == ""
