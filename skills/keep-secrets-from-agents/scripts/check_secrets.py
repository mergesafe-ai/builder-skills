#!/usr/bin/env python3
"""List the ways a coding agent in this project could read or leak its secrets.

Standard library only, no network. Reads the project's files and prints JSON
findings. It changes nothing: fixing is the skill's job.

It never prints a secret value. Secret files are read only to tell real values
from placeholders and to list key NAMES. Lines quoted from instruction files
are cut to the matched words and any token-looking text is replaced with
[redacted].

Checks:
  1. secret files (.env, keys, credential files): tracked by git? gitignored?
  2. agent read access per tool, through each tool's documented setting
     (Claude Code permissions.deny, Cursor .cursorignore, Gemini CLI
     .geminiignore; Codex and Copilot are reported, see not_checked)
  3. agent instruction files that point the agent at a secret file, or tell
     it to print secrets or the environment
  4. one secret file mixing a token the agent's task needs with other secrets

Usage:
    python3 check_secrets.py /path/to/repo > findings.json
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SKILL_NAME = "keep-secrets-from-agents"
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "env", "dist", "build", "__pycache__",
             ".next", ".nuxt", ".tox", ".mypy_cache", ".pytest_cache", "vendor", "target", ".terraform"}
MAX_BYTES = 1_000_000

TEMPLATE_SUFFIXES = ("example", "sample", "template", "tmpl", "dist", "defaults", "default", "schema", "test.example")
SSH_KEYS = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk"}

# Known token shapes. Used to classify values and to redact excerpts; never printed.
TOKEN_SHAPES = [
    ("GitLab token", r"glpat-[0-9A-Za-z_-]{16,}"),
    ("GitHub token", r"(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}"),
    ("AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("Slack token", r"xox[abposr]-[0-9A-Za-z-]{10,}"),
    ("API secret key", r"\bsk-(?:live_|test_|proj-|ant-)?[0-9A-Za-z_-]{16,}"),
    ("Stripe key", r"\b[rs]k_live_[0-9A-Za-z]{16,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("password in URL", r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
]
TOKEN_RE = re.compile("|".join(f"(?:{p})" for _, p in TOKEN_SHAPES))
LONG_OPAQUE = re.compile(r"[A-Za-z0-9+/_=-]{24,}")

SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|PASS\b|_PASS|CREDENTIAL|PRIVATE|AUTH|DSN|"
                         r"DATABASE_URL|CONN(ECTION)?_STR", re.I)
# Tokens an agent typically needs for a coding task (review, CI, issues).
TASK_TOKEN_NAME = re.compile(r"^(GITLAB|GL|GITHUB|GH|BITBUCKET|CI|JIRA|LINEAR|SENTRY_AUTH|NPM|PYPI|"
                             r"CODECOV|VERCEL|NETLIFY)_?[A-Z_]*(TOKEN|KEY|PAT)$|^GH_TOKEN$|^GITHUB_TOKEN$", re.I)
PLACEHOLDER = re.compile(r"^$|^(changeme|change_me|change-me|replace_?me|todo|tbd|none|null|nil|xxx+|\*+|\.\.\.|"
                         r"dummy|example|sample|placeholder|secret|password|token|key|test|foo|bar|"
                         r"your[-_ ].*|.*[-_ ]here|<.*>|\{\{.*\}\}|\$\{.*\}|\$[A-Z_]+|.*example\.com.*)$", re.I)


def finding(check, file, line, found, fix, tool=None):
    out = {"check": check, "file": file, "line": line, "found": found, "fix": fix}
    if tool:
        out["tool"] = tool
    return out


def read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            return ""
        return path.read_text(errors="replace")
    except OSError:
        return ""


def redact(text: str) -> str:
    text = TOKEN_RE.sub("[redacted]", text)
    return LONG_OPAQUE.sub("[redacted]", text)


def walk(repo: Path):
    for root, dirs, files in os.walk(repo):
        rel_root = Path(root).relative_to(repo)
        # Skip build and dependency folders, and copies of this skill (its own text mentions .env).
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (d == SKILL_NAME and "skills" in rel_root.parts)]
        for f in files:
            yield (Path(root) / f).relative_to(repo)


# ---------------------------------------------------------------- gitignore-style matching

def _glob_to_regex(pat: str) -> str:
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out += "/.*"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        elif pat[i] == "[":
            j = pat.find("]", i)
            if j == -1:
                out += re.escape(pat[i])
                i += 1
            else:
                out += pat[i:j + 1]
                i = j + 1
        else:
            out += re.escape(pat[i])
            i += 1
    return out


def gi_match(pattern: str, rel: str, anchored: bool | None = None) -> bool:
    """Does one gitignore-style pattern match the file at rel (posix, relative)?"""
    pat = pattern.strip()
    if not pat:
        return False
    dir_only = pat.endswith("/")
    pat = pat.rstrip("/")
    if anchored is None:
        anchored = "/" in pat
    pat = pat.lstrip("/")
    rx = re.compile(_glob_to_regex(pat) + "$")
    parts = rel.split("/")
    # A pattern matches the file itself, or any directory above it.
    candidates = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    if dir_only:
        candidates = candidates[:-1]
    for c in candidates:
        if anchored:
            if rx.match(c):
                return True
        elif rx.match(c.split("/")[-1]):
            return True
    return False


def ignore_file_covers(lines: list[str], rel: str) -> bool:
    covered = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            if gi_match(line[1:], rel):
                covered = False
        elif gi_match(line, rel):
            covered = True
    return covered


# ---------------------------------------------------------------- git

def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None


def is_git(repo: Path) -> bool:
    r = git(repo, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


def tracked_files(repo: Path) -> set[str]:
    r = git(repo, "ls-files", "-z")
    return set(r.stdout.split("\0")) - {""} if r and r.returncode == 0 else set()


def ever_committed(repo: Path, rel: str) -> bool:
    r = git(repo, "log", "--all", "--format=%H", "-1", "--", rel)
    return bool(r and r.returncode == 0 and r.stdout.strip())


def gitignored(repo: Path, rel: str) -> bool:
    r = git(repo, "check-ignore", "-q", "--no-index", rel)
    return bool(r and r.returncode == 0)


# ---------------------------------------------------------------- 1. secret files

def is_template(name: str) -> bool:
    low = name.lower()
    return any(low.endswith("." + s) or low.endswith("_" + s) or low.endswith("-" + s) for s in TEMPLATE_SUFFIXES)


def parse_env(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*[=:]\s*(.*)$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        val = m.group(2).strip()
        if val[:1] in "'\"" and val[-1:] == val[:1] and len(val) >= 2:
            val = val[1:-1]
        else:
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        out.append((m.group(1), val))
    return out


def real_secret(key: str, val: str) -> bool:
    if PLACEHOLDER.match(val.strip()):
        return False
    if TOKEN_RE.search(val):
        return True
    return bool(SECRET_NAME.search(key))


def classify(rel: Path, text_of) -> dict | None:
    """Return what kind of secret file this is, or None if it isn't one."""
    name = rel.name
    low = name.lower()
    if low == ".env" or low.startswith(".env.") or low.endswith(".env"):
        if low in (".envrc",):
            return None
        pairs = parse_env(text_of())
        secret_keys = [k for k, v in pairs if real_secret(k, v)]
        return {"kind": "env file", "template": is_template(name), "key_names": [k for k, _ in pairs],
                "secret_keys": secret_keys}
    if low == ".envrc":
        pairs = parse_env(text_of())
        secret_keys = [k for k, v in pairs if real_secret(k, v)]
        return {"kind": "env file", "template": False, "key_names": [k for k, _ in pairs],
                "secret_keys": secret_keys} if secret_keys else None
    if low in SSH_KEYS:
        return {"kind": "ssh private key"}
    if low.endswith((".pem", ".key")):
        return {"kind": "private key"} if "PRIVATE KEY" in text_of()[:4096] else None
    if low.endswith((".p12", ".pfx", ".jks", ".keystore")):
        return {"kind": "key store"}
    if low == "credentials.json" or low == "client_secret.json" or low.startswith("client_secret_"):
        return {"kind": "credentials file"}
    if low.endswith(".json") and ("service" in low or "account" in low or "key" in low or "cred" in low):
        t = text_of()
        if '"service_account"' in t and '"private_key"' in t:
            return {"kind": "service account key"}
    if low == "credentials" and rel.parent.name in (".aws",):
        return {"kind": "cloud credentials"}
    if low in (".npmrc", ".yarnrc.yml"):
        t = text_of()
        for m in re.finditer(r"(_authToken|_auth|_password|npmAuthToken)\s*[=:]\s*['\"]?([^\s'\"]+)", t):
            if not PLACEHOLDER.match(m.group(2)):
                return {"kind": "package registry token"}
        return None
    if low == ".pypirc":
        for m in re.finditer(r"^\s*password\s*[=:]\s*(\S+)", text_of(), re.M):
            if not PLACEHOLDER.match(m.group(1)):
                return {"kind": "package registry token"}
        return None
    if low in (".netrc", "_netrc"):
        return {"kind": "login file"} if re.search(r"\bpassword\s+\S+", text_of()) else None
    if low == ".git-credentials":
        return {"kind": "git credentials"}
    return None


def find_secret_files(repo: Path, in_git: bool) -> list[dict]:
    tracked = tracked_files(repo) if in_git else set()
    out = []
    for rel in walk(repo):
        info = classify(rel, lambda r=rel: read(repo / r))
        if not info:
            continue
        p = rel.as_posix()
        info = {"file": p, **info}
        if in_git:
            info["tracked"] = p in tracked
            info["gitignored"] = gitignored(repo, p)
            info["in_git_history"] = info["tracked"] or ever_committed(repo, p)
        else:
            info["tracked"] = info["gitignored"] = info["in_git_history"] = None
        out.append(info)
    return sorted(out, key=lambda f: f["file"])


def protected(f: dict) -> bool:
    """Secret files worth guarding: everything except templates holding only placeholders."""
    return not (f.get("template") and not f.get("secret_keys"))


def check_git(files: list[dict], in_git: bool) -> list[dict]:
    out = []
    for f in files:
        if f.get("template"):
            if f.get("secret_keys"):
                out.append(finding("template_has_values", f["file"], None,
                                   f"a template file holds real-looking values for: {', '.join(f['secret_keys'])}",
                                   "replace each value with a placeholder; if the file is in git, rotate those "
                                   "secrets"))
            continue
        if not in_git:
            continue
        if f["tracked"]:
            out.append(finding("tracked", f["file"], None, f"{f['kind']} is committed to git",
                               "stop tracking it (`git rm --cached`), gitignore it, and rotate every secret in "
                               "it: removing it from git does not undo the exposure"))
        elif f["in_git_history"]:
            out.append(finding("in_history", f["file"], None, f"{f['kind']} was committed in the past",
                               "rotate every secret it held; it is still in git history"))
        if not f["gitignored"]:
            out.append(finding("not_ignored", f["file"], None, f"{f['kind']} is not covered by .gitignore",
                               f"add `{suggest_pattern(f)}` to .gitignore"))
    return out


def suggest_pattern(f: dict) -> str:
    name = Path(f["file"]).name
    if f["kind"] == "env file":
        return ".env" if name == ".env" else (".env.*" if name.startswith(".env.") else name)
    if name.endswith(".pem"):
        return "*.pem"
    return name


# ---------------------------------------------------------------- 2. agent read access

def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def claude_rule_matches(content: str, rel: str, repo: Path) -> bool:
    """Does Read(content) cover the project file at rel? Per code.claude.com/docs/en/permissions."""
    c = content.strip()
    if c in ("", "*", "**", "./**", "/**", "**/*"):
        return True
    if c.startswith("//"):
        return gi_match(c[2:], (repo / rel).resolve().as_posix().lstrip("/"), anchored=True)
    if c.startswith("~/"):
        home = Path.home().as_posix().lstrip("/")
        return gi_match(home + "/" + c[2:], (repo / rel).resolve().as_posix().lstrip("/"), anchored=True)
    if c.startswith("./"):
        # Anchored at the project root. (Treated as anchored even for a bare filename,
        # so a nested copy is reported as uncovered rather than assumed safe.)
        return gi_match(c[2:], rel, anchored=True)
    if c.startswith("/"):
        return gi_match(c[1:], rel, anchored=True)
    return gi_match(c, rel)


def claude_read_denied(rules: list[str], rel: str, repo: Path) -> bool:
    denied = False
    for r in rules:
        if r == "Read":
            return True
        m = re.fullmatch(r"Read\((.*)\)", r)
        if not m:
            continue
        content = m.group(1)
        if content.startswith("!"):
            if denied and claude_rule_matches(content[1:], rel, repo):
                denied = False
        elif claude_rule_matches(content, rel, repo):
            denied = True
    return denied


def bash_rule_matches(content: str, cmd: str) -> bool:
    c = content.strip()
    if c in ("", "*"):
        return True
    if c.endswith(":*"):
        c = c[:-2] + " *"
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in c)
    if re.fullmatch(rx, cmd):
        return True
    # "A * at the end, with a space before it, also matches the bare command" (only wildcard).
    return c.endswith(" *") and c.count("*") == 1 and cmd == c[:-2]


ENV_DUMPS = ["env", "printenv", "printenv AWS_SECRET_ACCESS_KEY"]
CLAUDE_SETTINGS = [".claude/settings.json", ".claude/settings.local.json"]


def check_claude(repo: Path, files: list[dict], needed: bool) -> tuple[list, dict]:
    out, deny_by_file = [], {}
    for s in CLAUDE_SETTINGS:
        data = load_json(repo / s)
        if data is None:
            if (repo / s).exists():
                out.append(finding("claude_settings_invalid", s, None, "settings file is not valid JSON, so "
                                   "Claude Code skips it and none of its deny rules apply",
                                   "fix the JSON (no comments, no trailing commas)", tool="claude_code"))
            continue
        deny = (data.get("permissions") or {}).get("deny") or []
        deny_by_file[s] = [r for r in deny if isinstance(r, str)]
    rules = [r for s in CLAUDE_SETTINGS for r in deny_by_file.get(s, [])]
    shared = deny_by_file.get(".claude/settings.json", [])
    status = {"settings_files": sorted(deny_by_file), "read_denied": {}, "env_dump_denied": {}}

    if (repo / ".claudeignore").exists():
        out.append(finding("claudeignore", ".claudeignore", None,
                           "Claude Code does not read .claudeignore; its entries have no effect",
                           "move its entries into `Read(...)` deny rules in .claude/settings.json",
                           tool="claude_code"))
    for f in files:
        if not protected(f):
            continue
        ok = claude_read_denied(rules, f["file"], repo)
        status["read_denied"][f["file"]] = ok
        if not ok:
            out.append(finding("claude_read", f["file"], None,
                               "Claude Code can read this file: no `Read(...)` deny rule covers it",
                               f"add `Read({claude_pattern(f)})` to permissions.deny in .claude/settings.json",
                               tool="claude_code"))
        elif not claude_read_denied(shared, f["file"], repo):
            out.append(finding("claude_read_local_only", f["file"], None,
                               "only .claude/settings.local.json denies this file, which protects only this "
                               "machine's user", "add the same rule to the shared .claude/settings.json",
                               tool="claude_code"))
    if needed:
        for cmd in ENV_DUMPS:
            ok = any(r in ("Bash", "Bash(*)") or
                     (re.fullmatch(r"Bash\((.*)\)", r) and bash_rule_matches(r[5:-1], cmd)) for r in rules)
            status["env_dump_denied"][cmd] = ok
        missing = [c for c, ok in status["env_dump_denied"].items() if not ok]
        if missing:
            out.append(finding("claude_env_dump", ".claude/settings.json", None,
                               "nothing stops Claude Code from printing the shell environment: "
                               + ", ".join(f"`{c}`" for c in missing) + " would run",
                               "add `Bash(env)` and `Bash(printenv *)` to permissions.deny", tool="claude_code"))
    return out, status


def claude_pattern(f: dict) -> str:
    name = Path(f["file"]).name
    if f["kind"] == "env file":
        return ".env" if name == ".env" else ".env.*" if name.startswith(".env.") else name
    if name.endswith(".pem"):
        return "*.pem"
    if name.endswith(".key"):
        return "*.key"
    return name


def cursor_in_use(repo: Path) -> bool:
    return any((repo / p).exists() for p in (".cursor", ".cursorignore", ".cursorrules", ".cursorindexingignore"))


# From cursor.com/docs/context/ignore-files: ignored by default, plus everything in .gitignore.
CURSOR_DEFAULTS = [".env*"]


def check_cursor(repo: Path, files: list[dict]) -> tuple[list, dict]:
    lines = read(repo / ".cursorignore").splitlines()
    out, status = [], {"cursorignore": (repo / ".cursorignore").exists(), "read_blocked": {}}
    for f in files:
        if not protected(f):
            continue
        rel = f["file"]
        default = any(gi_match(p, rel) for p in CURSOR_DEFAULTS) or bool(f.get("gitignored"))
        reopened = any(l.strip().startswith("!") and gi_match(l.strip()[1:], rel) for l in lines)
        ok = (default and not reopened) or ignore_file_covers(lines, rel)
        status["read_blocked"][rel] = ok
        if not ok:
            why = ("a `!` line in .cursorignore re-includes it" if reopened
                   else "it is neither gitignored, nor in Cursor's default list, nor in .cursorignore")
            out.append(finding("cursor_read", rel, None, f"Cursor's agent can read this file: {why}",
                               f"add `{claude_pattern(f)}` to .cursorignore" + (" and remove the `!` line"
                                                                               if reopened else ""),
                               tool="cursor"))
    return out, status


def gemini_in_use(repo: Path) -> bool:
    return any((repo / p).exists() for p in (".gemini", "GEMINI.md", ".geminiignore"))


def check_gemini(repo: Path, files: list[dict]) -> tuple[list, dict]:
    lines = read(repo / ".geminiignore").splitlines()
    out, status = [], {"geminiignore": (repo / ".geminiignore").exists(), "listed": {}}
    for f in files:
        if not protected(f):
            continue
        ok = ignore_file_covers(lines, f["file"])
        status["listed"][f["file"]] = ok
        if not ok:
            out.append(finding("gemini_read", f["file"], None, "not listed in .geminiignore",
                               f"add `{claude_pattern(f)}` to .geminiignore and restart Gemini CLI",
                               tool="gemini_cli"))
    return out, status


def check_codex(repo: Path, files: list[dict]) -> tuple[list, dict]:
    path = repo / ".codex" / "config.toml"
    status = {"project_config": path.exists(), "env_deny_rule": False}
    if not path.exists() or not any(protected(f) for f in files):
        return [], status
    try:
        cfg = tomllib.loads(read(path))
    except tomllib.TOMLDecodeError:
        cfg = {}
    for prof in (cfg.get("permissions") or {}).values():
        roots = ((prof or {}).get("filesystem") or {}).get(":workspace_roots") or {}
        if any(v == "deny" and ".env" in k for k, v in roots.items()):
            status["env_deny_rule"] = True
    if status["env_deny_rule"]:
        return [], status
    return [finding("codex_read", ".codex/config.toml", None,
                    "no permission profile here denies `.env` files to Codex's sandboxed commands",
                    "add a `\"**/*.env\" = \"deny\"` rule to a permission profile (see SKILL.md, Codex)",
                    tool="codex")], status


def copilot_in_use(repo: Path) -> bool:
    return (repo / ".github" / "copilot-instructions.md").exists() or (repo / ".github" / "instructions").is_dir()


# ---------------------------------------------------------------- 3. instruction files

INSTRUCTION_NAMES = {"agents.md", "claude.md", "claude.local.md", "gemini.md", ".cursorrules", ".windsurfrules",
                     "copilot-instructions.md", "skill.md", "agent.md"}
SECRET_REF = re.compile(r"(?<![\w-])(\.env(?:\.[\w-]+)*|\.envrc|credentials\.json|id_rsa|id_ed25519|[\w-]+\.pem|"
                        r"\.npmrc|\.pypirc|\.netrc|\.git-credentials|service[-_]account[\w-]*\.json)(?![\w-])", re.I)
USE_VERB = re.compile(r"\b(read|reads|reading|use|uses|using|open|load|loads|source|cat|print|echo|show|take|"
                      r"grab|get|fetch|pull|look up|find|copy the|paste|from)\b", re.I)
SECRET_WORD = re.compile(r"\b(token|tokens|key|keys|secret|secrets|password|passwords|credential|credentials|"
                         r"api[ _-]?key|pat)\b", re.I)
COMMAND_ON_SECRET = re.compile(r"\b(cat|less|more|head|tail|source|bat|type|grep)\s+(?:-\S+\s+)*\S*"
                               r"(\.env(?:\.[\w-]+)*|credentials\.json|id_rsa|\.pem)\b|(?:^|[\s`;&|(])\.\s+\S*\.env\b",
                               re.I)
ENV_DUMP = re.compile(r"`\s*(env|printenv(?:\s+\w+)?|export\s+-p|set)\s*`|^\s*(?:\$\s*)?(env|printenv)\s*$|"
                      r"\bprintenv\b|\b(print|dump|show|list|output|echo|display)\b[^.\n]{0,30}\b(the\s+)?"
                      r"(shell\s+)?environment(\s+variables)?\b|\becho\s+\"?\$\{?[A-Z_]*(TOKEN|KEY|SECRET|PASSWORD)",
                      re.I | re.M)


NEGATED = re.compile(r"\b(never|don't|do not|must not|mustn't|should not|shouldn't|not allowed to|avoid)\b", re.I)


def negated(line: str, m: re.Match) -> bool:
    """A line that forbids the action ("Never read .env") is a guard, not an instruction to do it."""
    return bool(NEGATED.search(line[:m.start()]))


def instruction_files(repo: Path) -> list[Path]:
    out = []
    for rel in walk(repo):
        p = rel.as_posix().lower()
        if rel.name.lower() in INSTRUCTION_NAMES:
            out.append(rel)
        elif p.startswith(".cursor/rules/") or p.startswith(".github/instructions/") \
                or p.startswith(".claude/commands/") or p.startswith(".claude/agents/") \
                or p.startswith(".gemini/") and p.endswith(".md"):
            out.append(rel)
    return sorted(out)


def excerpt(line: str, m: re.Match) -> str:
    start, end = max(0, m.start() - 40), min(len(line), m.end() + 40)
    return redact(line[start:end].strip())


def check_instructions(repo: Path, secret_names: set[str]) -> tuple[list, list[str], set[str], set[str]]:
    """Findings, files scanned, secret key names the files mention, secret file names they point at."""
    out, scanned, keys_named, pointed = [], [], set(), set()
    for rel in instruction_files(repo):
        text = read(repo / rel)
        if not text:
            continue
        p = rel.as_posix()
        scanned.append(p)
        for n, line in enumerate(text.splitlines(), 1):
            for kind, pattern in TOKEN_SHAPES:
                if re.search(pattern, line):
                    out.append(finding("secret_in_instructions", p, n,
                                       f"the instruction file itself contains a {kind}",
                                       "remove it from the file and rotate it"))
                    break
            for k in secret_names:
                if re.search(rf"\b{re.escape(k)}\b", line):
                    keys_named.add(k)
            refs = [r for r in SECRET_REF.finditer(line) if not is_template(r.group(1))]
            cmd = COMMAND_ON_SECRET.search(line)
            if cmd and not is_template(cmd.group(2) or ".env") and not negated(line, cmd):
                pointed.add(Path(cmd.group(2) or ".env").name)
                out.append(finding("instruction_reads_secret", p, n,
                                   f"tells the agent to run a command on a secret file: \"{excerpt(line, cmd)}\"",
                                   "remove the line; give the agent a task-scoped token instead (SKILL.md, step 5)"))
            elif refs and USE_VERB.search(line) and SECRET_WORD.search(line) and not negated(line, refs[0]):
                pointed.update(Path(r.group(1)).name for r in refs)
                out.append(finding("instruction_points_at_secret", p, n,
                                   f"points the agent at {refs[0].group(1)} for a secret: "
                                   f"\"{excerpt(line, refs[0])}\"",
                                   "replace with a task-scoped token the user creates (SKILL.md, step 5)"))
            dump = ENV_DUMP.search(line)
            if dump and not negated(line, dump):
                out.append(finding("instruction_dumps_env", p, n,
                                   f"tells the agent to print the environment or a secret: \"{excerpt(line, dump)}\"",
                                   "remove the line; if a value is needed, inject it only into the one command"))
    return out, scanned, keys_named, pointed


# ---------------------------------------------------------------- 4. mixed-purpose files

def check_mixed(files: list[dict], pointed: set[str], keys_named: set[str]) -> list[dict]:
    out = []
    for f in files:
        if f.get("kind") != "env file" or f.get("template"):
            continue
        keys = f.get("secret_keys") or []
        task = [k for k in keys if k in keys_named or TASK_TOKEN_NAME.search(k)]
        others = [k for k in keys if k not in task]
        is_pointed = Path(f["file"]).name in pointed
        # Mixed: the agent needs one token from this file, and the file holds other secrets too.
        # If the agent is told to read the file but no key is named, it gets every key: two or more is mixed.
        if (task and others) or (is_pointed and not task and len(others) > 1):
            out.append(finding("mixed_secret_file", f["file"], None,
                               "one file holds what the agent's task needs ("
                               + (", ".join(task) or "the agent is told to read this file")
                               + ") and secrets the task does not need (" + ", ".join(others) + ")",
                               "give the agent its own task-scoped token, kept outside this file; move the other "
                               "secrets out of the project (SKILL.md, steps 5-6)"))
    return out


# ---------------------------------------------------------------- main

def main(repo_arg: str) -> int:
    repo = Path(repo_arg).resolve()
    in_git = is_git(repo)
    files = find_secret_files(repo, in_git)
    secret_names = {k for f in files for k in f.get("secret_keys", [])}
    instr, scanned, keys_named, pointed = check_instructions(repo, secret_names)
    guarded = [f for f in files if protected(f)]
    needed = bool(guarded) or bool(instr)

    findings = check_git(files, in_git)
    claude, claude_status = check_claude(repo, files, needed)
    findings += claude
    tools = {"claude_code": claude_status}
    if cursor_in_use(repo):
        c, tools["cursor"] = check_cursor(repo, files)
        findings += c
    if gemini_in_use(repo):
        g, tools["gemini_cli"] = check_gemini(repo, files)
        findings += g
    if (repo / ".codex").exists():
        c, tools["codex"] = check_codex(repo, files)
        findings += c
    if copilot_in_use(repo) and guarded:
        tools["copilot"] = {"note": "Copilot content exclusion is set in the repository's GitHub settings, "
                                    "not in a file, so this script cannot see it"}
    findings += instr
    findings += check_mixed(files, pointed, keys_named)

    json.dump({
        "repo": str(repo),
        "git": in_git,
        "secret_files": files,
        "instruction_files_scanned": scanned,
        "agent_tools": tools,
        "findings": findings,
        "not_checked": "Values are never printed. User-level and managed settings (~/.claude/settings.json, "
                       "~/.codex/config.toml, Cursor's global ignore list) are not read; neither are Copilot "
                       "content exclusions, which live in GitHub settings. Secrets already in the shell "
                       "environment, and other ways an agent with a shell can read files, are not detected.",
    }, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
