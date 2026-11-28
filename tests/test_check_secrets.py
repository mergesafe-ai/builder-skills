"""Tests for skills/keep-secrets-from-agents/scripts/check_secrets.py: what it finds, and that it never prints a secret."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "keep-secrets-from-agents"
SCRIPT = SKILL / "scripts" / "check_secrets.py"
spec = importlib.util.spec_from_file_location("check_secrets", SCRIPT)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

# Distinctive fake values: none of them may ever appear in the script's output.
GITLAB = "gl-fake-review-token-0001"
DBPW = "Sup3rS3cretProdPw-913"
HR = "hr_live_9f8e7d6c5b4a3f2e1d0c"
BI = "bi-cs-77aa88bb99cc00dd11ee"
VALUES = [GITLAB, DBPW, HR, BI]

LEAKY_ENV = f"PORT=3000\nGITLAB_TOKEN={GITLAB}\nPROD_DB_PASSWORD={DBPW}\nHR_API_TOKEN={HR}\nBI_CLIENT_SECRET=\"{BI}\"\n"
SAFE_SETTINGS = json.dumps({"permissions": {"deny": [
    "Read(.env)", "Read(.env.*)", "Read(!.env.example)", "Bash(env)", "Bash(printenv *)"]}})


def make(root: Path, files: dict[str, str], git: bool = True, track: list[str] | None = None) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    if git:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "--", *(track if track is not None else ["."])], cwd=root, check=True)
    return root


def run(root: Path) -> tuple[dict, str]:
    out = subprocess.run(["python3", str(SCRIPT), str(root)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout), out.stdout + out.stderr


def checks(data: dict) -> list[str]:
    return sorted(f["check"] for f in data["findings"])


# ---------------------------------------------------------------- matching

@pytest.mark.parametrize("pattern,path,hit", [
    (".env", ".env", True), (".env", "config/.env", True), (".env.*", ".env.local", True),
    (".env.*", ".env", False), ("*.pem", "certs/server.pem", True), ("/.env", "config/.env", False),
    ("secrets/", "secrets/a.json", True), ("secrets/", "secrets", False), ("**/id_rsa", "a/b/id_rsa", True),
    ("config/*.json", "config/creds.json", True), ("config/*.json", "x/config/creds.json", False),
])
def test_gitignore_match(pattern, path, hit):
    assert cs.gi_match(pattern, path) is hit


@pytest.mark.parametrize("rules,path,denied", [
    (["Read(.env)"], ".env", True),
    (["Read(.env)"], "api/.env", True),                 # bare name: any depth
    (["Read(./.env)"], "api/.env", False),              # ./ anchors at the project root
    (["Read(./.env)"], ".env", True),
    (["Read(.env.*)"], ".env.production", True),
    (["Read(.env.*)", "Read(!.env.example)"], ".env.example", False),
    (["Read(!.env.example)", "Read(.env.*)"], ".env.example", True),  # a ! listed first carves nothing out
    (["Read(**/*.pem)"], "certs/a.pem", True),
    (["Read"], "anything/at/all", True),
    (["Edit(.env)"], ".env", False),
    ([], ".env", False),
])
def test_claude_read_rules(tmp_path, rules, path, denied):
    assert cs.claude_read_denied(rules, path, tmp_path) is denied


@pytest.mark.parametrize("rule,cmd,hit", [
    ("env", "env", True), ("env", "env FOO=1 node x.js", False), ("printenv *", "printenv", True),
    ("printenv *", "printenv AWS_SECRET_ACCESS_KEY", True), ("printenv:*", "printenv", True),
    ("printenv*", "printenv", True), ("*", "env", True), ("git *", "env", False),
])
def test_bash_rules(rule, cmd, hit):
    assert cs.bash_rule_matches(rule, cmd) is hit


@pytest.mark.parametrize("key,val,secret", [
    ("GITLAB_TOKEN", GITLAB, True), ("DB_PASSWORD", "hunter2-real", True), ("PORT", "3000", False),
    ("API_KEY", "", False), ("API_KEY", "your_api_key_here", False), ("API_KEY", "changeme", False),
    ("API_KEY", "<api key>", False), ("API_KEY", "${API_KEY}", False), ("DATABASE_URL", "postgres://u:pw@db/x", True),
    ("NODE_ENV", "production", False), ("SOME_SETTING", "mysql://app:pw-913@db/x", True),
])
def test_real_secret(key, val, secret):
    assert cs.real_secret(key, val) is secret


# ---------------------------------------------------------------- the NordLayer scenario

LEAKY = {
    ".env": LEAKY_ENV,
    ".env.example": "PORT=3000\nGITLAB_TOKEN=your_gitlab_token_here\nPROD_DB_PASSWORD=\nHR_API_TOKEN=changeme\n",
    "AGENTS.md": "# Agents\n\nWhen reviewing a merge request, use the GitLab token in `.env` (GITLAB_TOKEN).\n"
                 "If `.env` is missing, run `printenv` to find the token.\n",
    ".gitignore": "node_modules/\n",
    "README.md": "Copy `.env.example` to `.env` and fill in your API key.\n",
    "src/index.js": "console.log(process.env.PORT)\n",
}


def test_nordlayer_scenario_finds_every_problem(tmp_path):
    data, _ = run(make(tmp_path, LEAKY, track=["AGENTS.md", ".gitignore", "README.md", "src", ".env.example"]))
    found = checks(data)
    for c in ["not_ignored", "claude_read", "claude_env_dump", "instruction_points_at_secret",
              "instruction_dumps_env", "mixed_secret_file"]:
        assert c in found, c
    assert "tracked" not in found
    env = next(f for f in data["secret_files"] if f["file"] == ".env")
    assert env["secret_keys"] == ["GITLAB_TOKEN", "PROD_DB_PASSWORD", "HR_API_TOKEN", "BI_CLIENT_SECRET"]
    mixed = next(f for f in data["findings"] if f["check"] == "mixed_secret_file")
    assert "(GITLAB_TOKEN)" in mixed["found"] and "HR_API_TOKEN" in mixed["found"]
    # The template holds only placeholders: no finding for it, and it isn't guarded.
    assert not [f for f in data["findings"] if f["file"] == ".env.example"]


def test_never_prints_a_secret_value(tmp_path):
    files = dict(LEAKY)
    files["CLAUDE.md"] = f"Connect with postgres://admin:{DBPW}@db.internal/prod for the tests.\n"
    files[".npmrc"] = f"//registry.npmjs.org/:_authToken={HR}\n"
    files["deploy/key.pem"] = f"-----BEGIN RSA PRIVATE KEY-----\n{BI}\n-----END RSA PRIVATE KEY-----\n"
    files[".env.sample"] = f"DB_PASSWORD={DBPW}\n"
    data, text = run(make(tmp_path, files))
    for v in VALUES:
        assert v not in text
    assert "secret_in_instructions" in checks(data)
    assert "template_has_values" in checks(data)
    assert {f["file"] for f in data["secret_files"]} >= {".env", ".npmrc", "deploy/key.pem", ".env.sample"}


def test_tracked_secret_says_rotate(tmp_path):
    data, _ = run(make(tmp_path, {".env": LEAKY_ENV}))
    tracked = next(f for f in data["findings"] if f["check"] == "tracked")
    assert "rotate" in tracked["fix"]


def test_secret_once_committed_is_in_history(tmp_path):
    make(tmp_path, {".env": LEAKY_ENV, "a.txt": "x"})
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "a"], cwd=tmp_path, check=True)
    subprocess.run(["git", "rm", "-q", "--cached", ".env"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(".env\n")
    data, _ = run(tmp_path)
    assert "in_history" in checks(data) and "tracked" not in checks(data) and "not_ignored" not in checks(data)


# ---------------------------------------------------------------- already safe: nothing to do

def test_safe_project_has_no_findings(tmp_path):
    data, _ = run(make(tmp_path, {
        ".env": f"GITLAB_TOKEN={GITLAB}\n",
        ".env.example": "GITLAB_TOKEN=\n",
        ".gitignore": ".env\n.env.*\n!.env.example\n",
        ".claude/settings.json": SAFE_SETTINGS,
        "AGENTS.md": "Run `npm test`. Never read `.env` files.\n",
        "README.md": "Copy `.env.example` to `.env`.\n",
    }, track=[".env.example", ".gitignore", ".claude", "AGENTS.md", "README.md"]))
    assert data["findings"] == []
    assert data["agent_tools"]["claude_code"]["read_denied"] == {".env": True}


def test_no_secrets_no_findings(tmp_path):
    data, _ = run(make(tmp_path, {"README.md": "# app\n", "src/a.py": "print(1)\n"}))
    assert data["findings"] == [] and data["secret_files"] == []


def test_works_outside_git(tmp_path):
    data, _ = run(make(tmp_path, {".env": LEAKY_ENV}, git=False))
    assert data["git"] is False
    assert "claude_read" in checks(data) and "not_ignored" not in checks(data)


# ---------------------------------------------------------------- instructions

@pytest.mark.parametrize("line,check", [
    ("Use the GitLab token in `.env` to post comments.", "instruction_points_at_secret"),
    ("Read the API key from .env.local before calling Stripe.", "instruction_points_at_secret"),
    ("Run `cat .env` to see the credentials.", "instruction_reads_secret"),
    ("source .env && ./deploy.sh", "instruction_reads_secret"),
    ("If the token is missing, print the environment variables.", "instruction_dumps_env"),
    ("Run `env` and look for GITLAB_TOKEN.", "instruction_dumps_env"),
    ("echo $GITLAB_TOKEN to check it is set", "instruction_dumps_env"),
])
def test_instruction_lines_flagged(tmp_path, line, check):
    data, _ = run(make(tmp_path, {"CLAUDE.md": f"# Notes\n\n{line}\n"}))
    assert check in checks(data)


@pytest.mark.parametrize("line", [
    "Copy `.env.example` to `.env` and fill it in.",
    "Never read `.env` files.",
    "Add your API key to .env yourself.",
    "Set up the environment with `npm install`.",
    "Read `.env.example` to see which keys exist.",
    "Use the GITLAB_REVIEW_TOKEN environment variable. Never read .env or print environment variables.",
    "Do not run `cat .env` or `printenv`.",
])
def test_instruction_lines_not_flagged(tmp_path, line):
    data, _ = run(make(tmp_path, {"AGENTS.md": f"# Notes\n\n{line}\n"}))
    assert not [f for f in data["findings"] if f["check"].startswith("instruction")]


def test_rules_and_skills_are_scanned(tmp_path):
    data, _ = run(make(tmp_path, {
        ".cursor/rules/api.mdc": "Use the token in .env for the API.\n",
        ".claude/skills/deploy/SKILL.md": "Run `cat .env.production` first.\n",
        ".github/copilot-instructions.md": "Use the key from credentials.json.\n",
    }))
    files = {f["file"] for f in data["findings"] if f["check"].startswith("instruction")}
    assert files == {".cursor/rules/api.mdc", ".claude/skills/deploy/SKILL.md", ".github/copilot-instructions.md"}


def test_this_skill_is_not_flagged_when_installed(tmp_path):
    root = make(tmp_path, {"README.md": "x\n"}, git=False)
    shutil.copytree(SKILL, root / ".claude" / "skills" / "keep-secrets-from-agents")
    data, _ = run(root)
    assert data["findings"] == []


def test_this_repo_has_no_findings():
    data, _ = run(ROOT)
    assert data["findings"] == [], data["findings"]


# ---------------------------------------------------------------- other tools and files

def test_cursor_default_ignores_env_but_not_keys(tmp_path):
    data, _ = run(make(tmp_path, {".cursorrules": "be nice\n", ".env": LEAKY_ENV,
                                  "certs/server.pem": "-----BEGIN PRIVATE KEY-----\nabc\n"}))
    cursor = [f["file"] for f in data["findings"] if f["check"] == "cursor_read"]
    assert cursor == ["certs/server.pem"]
    (tmp_path / ".cursorignore").write_text("*.pem\n")
    data, _ = run(tmp_path)
    assert not [f for f in data["findings"] if f["check"] == "cursor_read"]


def test_cursorignore_negation_reopens_env(tmp_path):
    data, _ = run(make(tmp_path, {".cursorignore": "!.env\n", ".env": LEAKY_ENV}))
    assert [f["file"] for f in data["findings"] if f["check"] == "cursor_read"] == [".env"]


def test_gemini_ignore(tmp_path):
    data, _ = run(make(tmp_path, {"GEMINI.md": "hi\n", ".env": LEAKY_ENV}))
    assert "gemini_read" in checks(data)
    (tmp_path / ".geminiignore").write_text(".env\n")
    data, _ = run(tmp_path)
    assert "gemini_read" not in checks(data)


def test_codex_profile(tmp_path):
    data, _ = run(make(tmp_path, {".codex/config.toml": "model = 'x'\n", ".env": LEAKY_ENV}))
    assert "codex_read" in checks(data)
    (tmp_path / ".codex/config.toml").write_text(
        'default_permissions = "p"\n[permissions.p.filesystem.":workspace_roots"]\n"**/*.env" = "deny"\n')
    data, _ = run(tmp_path)
    assert "codex_read" not in checks(data)


def test_copilot_is_reported_not_checked(tmp_path):
    data, _ = run(make(tmp_path, {".github/copilot-instructions.md": "hi\n", ".env": LEAKY_ENV}))
    assert "GitHub settings" in data["agent_tools"]["copilot"]["note"]


def test_claudeignore_and_local_only(tmp_path):
    data, _ = run(make(tmp_path, {".claudeignore": ".env\n", ".env": LEAKY_ENV,
                                  ".claude/settings.local.json": SAFE_SETTINGS}))
    found = checks(data)
    assert "claudeignore" in found and "claude_read_local_only" in found and "claude_read" not in found


def test_registry_files_need_a_literal_token(tmp_path):
    data, _ = run(make(tmp_path, {".npmrc": "//registry.npmjs.org/:_authToken=${NPM_TOKEN}\n",
                                  ".pypirc": "[pypi]\nusername = __token__\n"}))
    assert data["secret_files"] == []


def test_invalid_settings_reported(tmp_path):
    data, _ = run(make(tmp_path, {".claude/settings.json": "{ // no\n}", ".env": LEAKY_ENV}))
    assert "claude_settings_invalid" in checks(data)
