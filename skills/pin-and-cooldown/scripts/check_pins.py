#!/usr/bin/env python3
"""List the places where a project could install a version nobody chose.

Standard library only. Reads the project root's manifests, lockfiles and
package-manager settings, its CI files and its Dockerfiles, and prints JSON
findings. It changes nothing: fixing is the skill's job.

Checks: cooldown setting, floating versions, lockfile committed and used in CI,
GitHub Actions and container images pinned, tools installed without a version,
and install scripts.

Usage:
    python3 check_pins.py /path/to/repo > findings.json
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

SHA40 = re.compile(r"[0-9a-f]{40}")
EXACT_NPM = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
NPM_LOCAL = ("workspace:", "file:", "link:", "portal:", "patch:")
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "dist", "build", ".claude"}
LOCKFILES = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock",
             "uv": "uv.lock", "poetry": "poetry.lock"}


def finding(check, file, line, found, fix):
    return {"check": check, "file": file, "line": line, "found": found, "fix": fix}


def read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def line_of(text: str, needle: str) -> int | None:
    for n, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return n
    return None


def norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------- which tools

def detect_managers(repo: Path) -> list[str]:
    pkg = load_json(repo / "package.json")
    pm = str(pkg.get("packageManager", ""))
    found = []
    if (repo / "pnpm-lock.yaml").exists() or pm.startswith("pnpm"):
        found.append("pnpm")
    if (repo / "yarn.lock").exists() or pm.startswith("yarn"):
        found.append("yarn")
    if (repo / "bun.lock").exists() or (repo / "bun.lockb").exists() or pm.startswith("bun"):
        found.append("bun")
    if pkg and not found:
        found.append("npm")
    pyproject = load_toml(repo / "pyproject.toml")
    tool = pyproject.get("tool", {})
    if (repo / "uv.lock").exists() or "uv" in tool:
        found.append("uv")
    if (repo / "poetry.lock").exists() or "poetry" in tool:
        found.append("poetry")
    if not {"uv", "poetry"} & set(found):
        if pyproject.get("project") or list(repo.glob("requirements*.txt")):
            found.append("pip")
    return found


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def yarn_berry(repo: Path) -> bool:
    pm = str(load_json(repo / "package.json").get("packageManager", ""))
    return (repo / ".yarnrc.yml").exists() or bool(re.match(r"yarn@[2-9]", pm))


# ---------------------------------------------------------------- 1. cooldown

def yaml_value(text: str, key: str) -> str | None:
    m = re.search(rf"^{key}\s*:\s*['\"]?([^'\"#\n]*)", text, re.M)
    return m.group(1).strip() if m else None


def ini_value(text: str, key: str) -> str | None:
    m = re.search(rf"^\s*{key}\s*=\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def check_cooldown(repo: Path, managers: list[str], ci_text: str) -> tuple[list, dict]:
    out, settings = [], {}
    npmrc = read(repo / ".npmrc")
    for m in managers:
        if m == "npm":
            v = ini_value(npmrc, "min-release-age") or ini_value(npmrc, "before")
            settings["npm"] = v
            if not v or v == "0":
                out.append(finding("cooldown", ".npmrc", None, "npm installs a version the minute it is published",
                                   "add `min-release-age=7` to .npmrc (days; needs npm 11.10 or later)"))
        elif m == "pnpm":
            ws = read(repo / "pnpm-workspace.yaml")
            v = yaml_value(ws, "minimumReleaseAge")
            settings["pnpm"] = v
            if not v or v == "0":
                out.append(finding("cooldown", "pnpm-workspace.yaml", None,
                                   "no minimumReleaseAge set (pnpm 11+ waits 1 day by default, and lets a "
                                   "too-new version through if nothing older fits; pnpm 10 and older do not wait)",
                                   "add `minimumReleaseAge: 10080` to pnpm-workspace.yaml (minutes = 7 days)"))
        elif m == "yarn":
            if not yarn_berry(repo):
                out.append(finding("cooldown", "yarn.lock", None, "Yarn 1 (classic) has no cooldown setting",
                                   "leave it; say so in the report (moving to Yarn 4 or pnpm would add one)"))
                continue
            v = yaml_value(read(repo / ".yarnrc.yml"), "npmMinimalAgeGate")
            settings["yarn"] = v
            if v in ("0", "0d"):
                out.append(finding("cooldown", ".yarnrc.yml", line_of(read(repo / ".yarnrc.yml"), "npmMinimalAgeGate"),
                                   "npmMinimalAgeGate is turned off", "set `npmMinimalAgeGate: 7d`"))
            elif not v:
                out.append(finding("cooldown", ".yarnrc.yml", None,
                                   "no npmMinimalAgeGate set (recent Yarn 4 defaults to 1w; older Yarn 4 has none)",
                                   "add `npmMinimalAgeGate: 7d` to .yarnrc.yml"))
        elif m == "bun":
            v = load_toml(repo / "bunfig.toml").get("install", {}).get("minimumReleaseAge")
            settings["bun"] = v
            if not v:
                out.append(finding("cooldown", "bunfig.toml", None, "bun installs a version the minute it is published",
                                   "add `[install]` `minimumReleaseAge = 604800` to bunfig.toml (seconds = 7 days)"))
        elif m == "uv":
            v = (load_toml(repo / "pyproject.toml").get("tool", {}).get("uv", {}).get("exclude-newer")
                 or load_toml(repo / "uv.toml").get("exclude-newer"))
            settings["uv"] = v
            if not v:
                out.append(finding("cooldown", "pyproject.toml", None, "uv resolves to the newest release, however new",
                                   'add `exclude-newer = "7 days"` under [tool.uv] (needs uv 0.9.17 or later)'))
        elif m == "poetry":
            v = load_toml(repo / "poetry.toml").get("solver", {}).get("min-release-age")
            settings["poetry"] = v
            if not v:
                out.append(finding("cooldown", "poetry.toml", None, "Poetry resolves to the newest release, however new",
                                   "add `[solver]` `min-release-age = 7` to poetry.toml (days; needs Poetry 2.4)"))
        elif m == "pip":
            v = ("uploaded-prior-to" in ci_text or "PIP_UPLOADED_PRIOR_TO" in ci_text
                 or "uploaded-prior-to" in read(repo / "pip.conf"))
            settings["pip"] = v or None
            if not v:
                out.append(finding("cooldown", "requirements.txt", None, "pip installs a version the minute it is published",
                                   "set `PIP_UPLOADED_PRIOR_TO: P7D` where CI runs pip (days; needs pip 26.1)"))
    return out, settings


# ---------------------------------------------------------------- 2. floating

def npm_resolved(repo: Path) -> dict[str, str]:
    lock = load_json(repo / "package-lock.json")
    got = {k.rsplit("node_modules/", 1)[-1]: v.get("version") for k, v in lock.get("packages", {}).items()
           if k.startswith("node_modules/") and "/node_modules/" not in k}
    text = read(repo / "pnpm-lock.yaml")
    m = re.search(r"^importers:\n(?:\s*\n)*  \.:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    name = None
    for line in (m.group(1).splitlines() if m else []):
        if re.match(r"^      \S", line):
            name = line.strip().rstrip(":").strip("'\"")
        elif name and line.strip().startswith("version:"):
            got[name] = line.split(":", 1)[1].strip().split("(")[0].strip("'\"")
    return {k: v for k, v in got.items() if v}


def npm_pinned(spec: str) -> bool:
    spec = spec.strip()
    if spec.startswith(NPM_LOCAL):
        return True
    if spec.startswith("npm:"):
        spec = spec.rsplit("@", 1)[-1]
    if "://" in spec or spec.startswith(("github:", "gitlab:", "bitbucket:", "git+")) or re.match(r"^[\w-]+/[\w.-]+(#.*)?$", spec):
        return bool(SHA40.fullmatch(spec.rsplit("#", 1)[-1])) if "#" in spec else False
    return bool(EXACT_NPM.fullmatch(spec))


def check_npm_floating(repo: Path) -> list:
    pkg_text = read(repo / "package.json")
    pkg = load_json(repo / "package.json")
    resolved = npm_resolved(repo)
    out = []
    # peerDependencies are ranges on purpose: they say what the package works with.
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in pkg.get(section, {}).items():
            if not npm_pinned(str(spec)):
                have = resolved.get(name)
                fix = f'pin to "{have}" (what the lockfile installs today)' if have else \
                    "pin to the exact version installed now (run `npm ls <name>` or read the lockfile); never pick a newer one"
                out.append(finding("floating", "package.json", line_of(pkg_text, f'"{name}"'),
                                   f'{section}: "{name}": "{spec}"', fix))
    return out


REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def py_pinned(req: str) -> bool:
    req = req.split(";", 1)[0].strip()
    m = REQ.match(req)
    if not m:
        return True
    spec = m.group(3).strip()
    if spec.startswith("@"):
        ref = spec.rsplit("@", 1)[-1]
        return bool(SHA40.fullmatch(ref)) or bool(re.search(r"sha256=[0-9a-f]{64}", spec))
    return bool(re.fullmatch(r"===?\s*[^,*\s]+", spec))


def py_resolved(repo: Path) -> dict[str, str]:
    got = {}
    for lock in ("uv.lock", "poetry.lock"):
        for p in load_toml(repo / lock).get("package", []):
            got[norm_py(p.get("name", ""))] = p.get("version")
    return got


def check_py_floating(repo: Path) -> list:
    out, resolved = [], py_resolved(repo)

    def fix_for(req):
        m = REQ.match(req.split(";", 1)[0].strip())
        have = resolved.get(norm_py(m.group(1))) if m else None
        return (f"pin to =={have} (what the lockfile installs today)" if have else
                "pin with == to the version installed now (`pip freeze` or the lockfile); never pick a newer one")

    text = read(repo / "pyproject.toml")
    data = load_toml(repo / "pyproject.toml")
    proj = data.get("project", {})
    groups = [("project.dependencies", proj.get("dependencies", []))]
    groups += [(f"optional-dependencies.{k}", v) for k, v in proj.get("optional-dependencies", {}).items()]
    groups += [(f"dependency-groups.{k}", v) for k, v in data.get("dependency-groups", {}).items()]
    for where, reqs in groups:
        for req in reqs:
            if isinstance(req, str) and not py_pinned(req):
                out.append(finding("floating", "pyproject.toml", line_of(text, req), f"{where}: {req}", fix_for(req)))
    poetry = data.get("tool", {}).get("poetry", {})
    tables = [("tool.poetry.dependencies", poetry.get("dependencies", {}))]
    tables += [(f"tool.poetry.group.{g}", v.get("dependencies", {})) for g, v in poetry.get("group", {}).items()]
    for where, deps in tables:
        for name, spec in deps.items():
            ver = spec.get("version") if isinstance(spec, dict) else spec
            if name == "python" or ver is None:
                continue
            if not re.fullmatch(r"=?=?\s*\d[\w.+-]*", str(ver)):
                have = resolved.get(norm_py(name))
                out.append(finding("floating", "pyproject.toml", line_of(text, name), f'{where}: {name} = "{ver}"',
                                   f'pin to "{have}" (what poetry.lock installs today)' if have else
                                   "pin to the exact version poetry.lock installs today"))
    for path in sorted(repo.glob("requirements*.txt")):
        rtext = read(path)
        for n, line in enumerate(rtext.splitlines(), 1):
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith(("#", "-r", "-c", "--")) or line in (".", "-e ."):
                continue
            if not py_pinned(line.removeprefix("-e ").strip()):
                out.append(finding("floating", path.name, n, line, fix_for(line)))
    return out


# ---------------------------------------------------------------- 3. lockfile

def git(repo: Path, *args) -> int:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True).returncode
    except OSError:
        return 2


def check_lockfiles(repo: Path, managers: list[str]) -> list:
    out = []
    in_git = git(repo, "rev-parse", "--git-dir") == 0
    for m in managers:
        if m == "pip":
            continue  # plain pip has no lockfile of its own; exact pins in requirements.txt stand in for one
        names = ["bun.lock", "bun.lockb"] if m == "bun" else [LOCKFILES[m]]
        lock = next((n for n in names if (repo / n).exists()), None)
        if not lock:
            out.append(finding("lockfile", names[0], None, f"no {names[0]}: every install picks versions afresh",
                               f"create it with the tool's lock or install command, then commit it"))
            continue
        if not in_git:
            continue
        if git(repo, "check-ignore", "-q", lock) == 0:
            out.append(finding("lockfile", lock, None, f"{lock} is gitignored, so CI and teammates never see it",
                               "remove its line from .gitignore and commit the lockfile"))
        elif git(repo, "ls-files", "--error-unmatch", lock) != 0:
            out.append(finding("lockfile", lock, None, f"{lock} is not committed", "commit it"))
    return out


def ci_files(repo: Path) -> list[Path]:
    pats = [".github/workflows/*.yml", ".github/workflows/*.yaml", ".github/actions/*/action.yml",
            ".gitlab-ci.yml", ".circleci/config.yml", "**/Dockerfile*", "**/*.dockerfile",
            "**/docker-compose*.yml", "**/docker-compose*.yaml", "**/compose*.yml", "**/compose*.yaml"]
    seen = []
    for pat in pats:
        for p in sorted(repo.glob(pat)):
            if p.is_file() and not SKIP_DIRS & set(p.relative_to(repo).parts) and p not in seen:
                seen.append(p)
    return seen


def is_dockerfile(p: Path) -> bool:
    return p.name.startswith("Dockerfile") or p.suffix == ".dockerfile"


def after(cmd: str, pattern: str) -> list[str] | None:
    """The non-flag words after a command, or None when the command is not there."""
    m = re.search(rf"(?:^|[\s:'\"]){pattern}(?=\s|$)(.*)", cmd)
    return None if m is None else [w for w in m.group(1).split() if not w.startswith("-")]


def check_ci_installs(repo: Path, files: list[Path]) -> list:
    """Install commands that ignore the lockfile. Docker builds don't set CI=true, so the
    'frozen in CI by default' rule of pnpm and Yarn 4 does not hold there."""
    out = []
    for p in files:
        rel, docker = str(p.relative_to(repo)), is_dockerfile(p)
        if "compose" in p.name:
            continue
        for n, line in enumerate(read(p).splitlines(), 1):
            for c in re.split(r"&&|;|\|\|", line):
                c = " ".join(c.split())
                if after(c, r"npm (?:install|i)") == [] and not re.search(r"\s(-g|--global)\b", c):
                    out.append(finding("lockfile", rel, n, c, "use `npm ci`: it installs exactly what package-lock.json says"))
                elif after(c, r"pnpm (?:install|i)") is not None and docker and "--frozen-lockfile" not in c:
                    out.append(finding("lockfile", rel, n, c, "add `--frozen-lockfile`"))
                elif after(c, r"yarn(?: install)?") == [] and "--frozen-lockfile" not in c and "--immutable" not in c \
                        and (docker or not yarn_berry(repo)):
                    out.append(finding("lockfile", rel, n, c, "add `--immutable` (Yarn 4) or `--frozen-lockfile` (Yarn 1)"))
                elif after(c, r"bun (?:install|i)") == [] and "--frozen-lockfile" not in c:
                    out.append(finding("lockfile", rel, n, c, "add `--frozen-lockfile`"))
                elif after(c, r"uv sync") is not None and "--locked" not in c and "--frozen" not in c:
                    out.append(finding("lockfile", rel, n, c, "add `--locked` (fails if uv.lock is out of date)"))
    return out


# ---------------------------------------------------------------- 4. CI pinned

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?([^\s'\"#]+)['\"]?\s*(#.*)?$")
IMAGE = re.compile(r"^\s*(?:-\s*)?(?:image|container):\s*['\"]?([^\s'\"#{]+)")
FROM = re.compile(r"^\s*FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?", re.I)
PIPE_SH = re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b")
TOOL = re.compile(r"\b(pip3?|python3? -m pip|uv pip|pipx|uv tool) install\s+(.*)|"
                  r"\bnpm (?:install|i) (?:-g|--global)\s+(.*)|\bgo install\s+(\S+@latest)")


def image_pinned(ref: str) -> bool:
    return "@sha256:" in ref


def check_pinned_ci(repo: Path, files: list[Path]) -> list:
    out = []
    for p in files:
        rel, text = str(p.relative_to(repo)), read(p)
        stages = set()
        for n, line in enumerate(text.splitlines(), 1):
            if is_dockerfile(p):
                m = FROM.match(line)
                if m:
                    img = m.group(1)
                    if m.group(2):
                        stages.add(m.group(2).lower())
                    if img.lower() not in stages and img != "scratch" and not image_pinned(img):
                        out.append(finding("image", rel, n, line.strip(),
                                           "can't tell: the image comes from a build ARG; pin the ARG's default by digest"
                                           if "$" in img else f"pin by digest: {img}@sha256:<digest of the image you use today>"))
            m = USES.match(line)
            if m and not m.group(1).startswith("./"):
                ref = m.group(1)
                if ref.startswith("docker://"):
                    if not image_pinned(ref):
                        out.append(finding("action", rel, n, line.strip(), "pin the image by @sha256: digest"))
                elif "@" in ref:
                    sha = ref.rsplit("@", 1)[1]
                    if not SHA40.fullmatch(sha):
                        out.append(finding("action", rel, n, line.strip(),
                                           f"use the full commit SHA that {sha} points to now, with `# <version>` after it"))
                    elif not m.group(2):
                        out.append(finding("action", rel, n, line.strip(), "pinned; add a `# vX.Y.Z` comment so people can read it"))
            m = IMAGE.match(line)
            if m and not is_dockerfile(p) and not image_pinned(m.group(1)):
                out.append(finding("image", rel, n, line.strip(), f"pin by digest: {m.group(1)}@sha256:<digest>"))
            if PIPE_SH.search(line):
                out.append(finding("tool", rel, n, line.strip(),
                                   "downloads a script and runs it unseen: use the tool's official setup action pinned "
                                   "by SHA, or a versioned download URL"))
            m = TOOL.search(line)
            if m:
                rest = m.group(2) or m.group(3) or ""
                names = [w for w in re.split(r"\s+", rest.split("&&")[0].split(";")[0].strip())
                         if w and not w.startswith(("-", ".", "/", "$")) and not w.endswith((".txt", ".toml", ".whl"))]
                prev_flag = re.findall(r"(?:-r|-c|--requirement|--constraint)\s+(\S+)", rest)
                names = [w for w in names if w not in prev_flag]
                loose = [w for w in names if ("==" not in w and not re.search(r"@\d", w))]
                if m.group(4) or loose:
                    out.append(finding("tool", rel, n, line.strip(),
                                       "install an exact version (`name==1.2.3` / `name@1.2.3`)"))
    return out


# ---------------------------------------------------------------- 5. scripts

def check_scripts(repo: Path, managers: list[str]) -> list:
    out = []
    if "npm" in managers and ini_value(read(repo / ".npmrc"), "ignore-scripts") != "true":
        out.append(finding("scripts", ".npmrc", None,
                           "npm runs every dependency's install script (a common way malware gets in)",
                           "add `ignore-scripts=true` to .npmrc; packages that build native code may then need "
                           "`npm rebuild <name>` or a step of their own"))
    ws = read(repo / "pnpm-workspace.yaml")
    if "pnpm" in managers and yaml_value(ws, "dangerouslyAllowAllBuilds") == "true":
        out.append(finding("scripts", "pnpm-workspace.yaml", line_of(ws, "dangerouslyAllowAllBuilds"),
                           "dangerouslyAllowAllBuilds: true lets every dependency run install scripts",
                           "remove it and list only the packages that need builds under `allowBuilds:`"))
    yrc = read(repo / ".yarnrc.yml")
    if "yarn" in managers and yaml_value(yrc, "enableScripts") == "true":
        out.append(finding("scripts", ".yarnrc.yml", line_of(yrc, "enableScripts"),
                           "enableScripts: true runs every dependency's install script",
                           "set `enableScripts: false` and turn scripts on per package with `dependenciesMeta`"))
    return out


# Oldest version of each tool that understands the cooldown setting above.
MIN_VERSION = {"npm": (11, 10), "pnpm": (10, 16), "bun": (1, 3), "uv": (0, 9, 17), "poetry": (2, 4), "pip": (26, 1)}
VERSION_CMD = {"pip": [sys.executable, "-m", "pip", "--version"]}


def parse_version(text: str) -> tuple | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def check_tool_versions(managers: list[str]) -> list[str]:
    """Warnings for tools on this machine too old to honour a cooldown setting."""
    out = []
    for m in managers:
        if m not in MIN_VERSION:
            continue
        try:
            got = subprocess.run(VERSION_CMD.get(m, [m, "--version"]), capture_output=True, text=True, timeout=30)
            have = parse_version(got.stdout)
        except (OSError, subprocess.TimeoutExpired):
            continue  # not installed here: nothing to say about this machine
        need = MIN_VERSION[m]
        if have and have < need:
            out.append(f"{m} on this machine is {'.'.join(map(str, have))}; its cooldown setting needs "
                       f"{'.'.join(map(str, need))} or later, and older versions ignore it")
    return out


def main(repo_arg: str) -> int:
    repo = Path(repo_arg).resolve()
    managers = detect_managers(repo)
    files = ci_files(repo)
    ci_text = "\n".join(read(p) for p in files)
    cooldown, settings = check_cooldown(repo, managers, ci_text)
    findings = cooldown
    if set(managers) & {"npm", "pnpm", "yarn", "bun"}:
        findings += check_npm_floating(repo)
    if set(managers) & {"uv", "poetry", "pip"}:
        findings += check_py_floating(repo)
    findings += check_lockfiles(repo, managers)
    findings += check_ci_installs(repo, files)
    findings += check_pinned_ci(repo, files)
    findings += check_scripts(repo, managers)
    json.dump({
        "repo": str(repo),
        "package_managers": managers,
        "cooldown_settings": settings,
        "files_scanned": [str(p.relative_to(repo)) for p in files],
        "findings": findings,
        "warnings": check_tool_versions(managers),
        "not_checked": "Only the project root's manifests are read (not sub-packages of a monorepo). "
                       "Only npm, pnpm, Yarn, bun, uv, Poetry and pip are known.",
    }, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
