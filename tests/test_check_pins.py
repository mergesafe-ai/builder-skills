"""Tests for skills/pin-and-cooldown/scripts/check_pins.py: what counts as pinned, and what gets flagged."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "pin-and-cooldown" / "scripts" / "check_pins.py"
spec = importlib.util.spec_from_file_location("check_pins", SCRIPT)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize("version,pinned", [
    ("1.7.0", True), ("1.0.0-beta.2", True), ("workspace:*", True), ("file:../lib", True),
    ("npm:lodash@4.17.21", True), (f"github:user/repo#{SHA}", True),
    ("^1.7.0", False), ("~4.21.0", False), ("latest", False), ("*", False), (">=1.0.0", False),
    ("1.x", False), ("github:user/repo#main", False), ("user/repo", False), ("https://x.test/a.tgz", False),
])
def test_npm_pinned(version, pinned):
    assert cp.npm_pinned(version) is pinned


@pytest.mark.parametrize("req,pinned", [
    ("flask==3.1.3", True), ("flask[async]==3.1.3; python_version>'3.10'", True),
    (f"lib @ git+https://x.test/lib.git@{SHA}", True),
    ("flask", False), ("flask>=3.0", False), ("pytest~=8.0", False), ("flask==3.*", False),
    ("lib @ git+https://x.test/lib.git@main", False),
])
def test_py_pinned(req, pinned):
    assert cp.py_pinned(req) is pinned


def git_repo(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def findings(root: Path) -> list[dict]:
    out = subprocess.run(["python3", str(SCRIPT), str(root)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["findings"]


LOCK = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/axios": {"version": "1.21.1"}}})


def test_floating_node_project_lists_every_problem(tmp_path):
    root = git_repo(tmp_path, {
        "package.json": json.dumps({"name": "a", "private": True, "dependencies": {"axios": "^1.7.0"},
                                    "peerDependencies": {"react": ">=18"}}),
        "package-lock.json": LOCK,
        ".gitignore": "package-lock.json\n",
        ".github/workflows/ci.yml": "steps:\n  - uses: actions/checkout@v4\n  - run: npm install\n"
                                    "  - run: npm install -g typescript\n",
        "Dockerfile": "FROM node:20 AS build\nRUN npm ci\nFROM build\n",
    })
    got = {(f["check"], f["file"], f["line"]) for f in findings(root)}
    assert got == {
        ("cooldown", ".npmrc", None), ("scripts", ".npmrc", None),
        ("floating", "package.json", 1),          # axios only: peer ranges are fine
        ("lockfile", "package-lock.json", None),  # gitignored
        ("action", ".github/workflows/ci.yml", 2),
        ("lockfile", ".github/workflows/ci.yml", 3),  # npm install, not npm ci
        ("tool", ".github/workflows/ci.yml", 4),      # global install with no version
        ("image", "Dockerfile", 1),                   # `FROM build` is a stage, not an image
    }
    axios = next(f for f in findings(root) if f["check"] == "floating")
    assert '"1.21.1"' in axios["fix"]  # pins to what the lockfile has, never newer


def test_pinned_project_has_no_findings(tmp_path):
    root = git_repo(tmp_path, {
        "package.json": json.dumps({"name": "a", "private": True, "dependencies": {"axios": "1.21.1"}}),
        "package-lock.json": LOCK,
        ".npmrc": "min-release-age=7\nignore-scripts=true\n",
        ".github/workflows/ci.yml": f"steps:\n  - uses: actions/checkout@{SHA} # v4.2.2\n  - run: npm ci\n",
        "Dockerfile": f"FROM node:20@{DIGEST}\nRUN npm ci\n",
    })
    assert findings(root) == []


def test_uv_project_pins_from_uv_lock(tmp_path):
    root = git_repo(tmp_path, {
        "pyproject.toml": '[project]\nname = "a"\nversion = "0.1.0"\ndependencies = ["Flask>=3.0"]\n'
                          '[tool.uv]\nexclude-newer = "7 days"\n',
        "uv.lock": 'version = 1\n[[package]]\nname = "flask"\nversion = "3.1.3"\n',
        "Dockerfile": f"FROM python:3.12@{DIGEST}\nRUN uv sync --locked\n",
        ".github/workflows/ci.yml": "steps:\n  - run: uv sync\n",
    })
    got = findings(root)
    assert [(f["check"], f["file"]) for f in got] == [("floating", "pyproject.toml"),
                                                        ("lockfile", ".github/workflows/ci.yml")]
    assert "==3.1.3" in got[0]["fix"]
