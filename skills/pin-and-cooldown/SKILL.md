---
name: pin-and-cooldown
description: Locks a project's dependencies so a hijacked release can't slip in on the next install. Pins every version exactly, waits a few days before taking new releases, makes CI install from the committed lockfile, and pins GitHub Actions by commit and container images by digest. Use when asked to pin or lock dependencies, stop using latest or version ranges, add a release cooldown or minimum release age, pin Actions or Docker images, or protect a project against supply-chain attacks. Also use when adding a dependency or writing CI install steps, so the new one goes in pinned. Checking for known vulnerabilities is cve-reachability.
---

# Pin your dependencies and wait before taking new releases

On 2026-03-31, two infected axios versions (1.14.1 and 0.30.4) were on npm for
about three hours, published from a hijacked maintainer account. Anyone whose
project said `"axios": "^1.7.0"` or `latest` and ran `npm install` in that
window got a remote-access trojan. Two habits would have skipped them:

- **Exact pins**: the project names one version, so nothing new arrives without someone choosing it.
- **A cooldown**: the package manager ignores versions younger than a few days. Hijacked releases are usually spotted and pulled within hours.

Words used below:

- **Lockfile**: the file listing the exact version of every package installed, including the ones your dependencies pull in (`package-lock.json`, `pnpm-lock.yaml`, `uv.lock`...).
- **Commit SHA**: the 40-character id of one exact commit. A tag like `v4` can be moved to other code; a SHA can't.
- **Digest**: the same idea for a container image, `@sha256:...`.

## Two ways in

- **The user asked** to pin, lock down or harden the project: do the whole check below.
- **You are adding one dependency or writing a CI install step**: do only that part, pinned. Don't audit the rest of the project unasked; at most, mention in one line that this skill can check the rest.
  - New package: pick a version at least 7 days old (or the project's cooldown, if it sets a longer one). `npm view <pkg> dist-tags.latest` gives the newest version and `npm view <pkg> time --json` the date of every version; on PyPI, the release history page. If the newest is too young, take the one before it. Add it exactly: `npm install <pkg>@<version> --save-exact`, `pnpm add -E <pkg>@<version>`, `uv add "<pkg>==<version>"`.
  - New CI step: install from the lockfile and pin any action or image you add (Actions and Images under step 5).

## Steps (whole check)

1. From the project root, run `python3 <skill-dir>/scripts/check_pins.py .`
   It prints JSON: the package managers it found, their cooldown settings, and a list of findings. It changes nothing.
   `warnings` lists tools on this machine too old to honour a cooldown setting. Always pass them on.
2. Check for security fixes the cooldown would hold back (see "A cooldown never blocks a security fix" below). Do this even when `findings` is empty.
3. If `findings` is empty and step 2 found no fix the cooldown blocks, tell the user the project is already pinned, name the checks that passed, pass on any `warnings` and any holes step 2 found (with their fixed versions), and stop. Change nothing, and skip steps 4-7.
4. Otherwise, show the user the list of changes you would make, grouped by the checks below, plus any security-fix exception from step 2, in plain language. **Ask before changing anything**, unless the user already said to just do it. A security-fix exception that moves a package to a newer version is an upgrade: always ask for that one, even after "just do it".
5. Apply what they agreed to, check by check:

   **Cooldown** (`check: cooldown`). Default 7 days. A cooldown the project already sets, shorter or longer, is its choice: leave it and mention it. Use the setting the finding names; units differ per tool:

   | Tool | Where | Setting for 7 days |
   |---|---|---|
   | npm 11.10+ | `.npmrc` | `min-release-age=7` (days) |
   | pnpm | `pnpm-workspace.yaml` | `minimumReleaseAge: 10080` (minutes; pnpm 11+ defaults to 1440, one day) |
   | Yarn 4 | `.yarnrc.yml` | `npmMinimalAgeGate: 7d` |
   | bun | `bunfig.toml` `[install]` | `minimumReleaseAge = 604800` (seconds) |
   | uv 0.9.17+ | `pyproject.toml` `[tool.uv]` | `exclude-newer = "7 days"` |
   | Poetry 2.4+ | `poetry.toml` `[solver]` | `min-release-age = 7` (days) |
   | pip 26.1+ | CI env or `pip.conf` | `PIP_UPLOADED_PRIOR_TO=P7D` |

   Yarn 1 has no cooldown: say so, don't invent one. If `warnings` says the tool here is too old, still add the setting and tell the user which version it needs: an older version ignores it, a newer one obeys it. The cooldown matters most on developer machines, where the lockfile gets updated; CI installing from the lockfile already gets fixed versions.

   **Floating versions** (`check: floating`). Replace each range, `latest`, `*` or branch with the exact version the lockfile installs today (the finding gives it). Never pick a newer version. Then refresh only the lockfile's own record of the manifest (`npm install --package-lock-only`, `pnpm install --lockfile-only`, `uv lock`) and check that only the project's own entry changed: `git diff` on the lockfile should show no other `version` line (a lockfile not yet in git: copy it first and `diff` against the copy). If any version changed, undo and tell the user. If the finding has no lockfile version, read it from `npm ls`, `pip freeze` or the installed packages; if you can't find it, leave that line and say why.

   **Lockfile** (`check: lockfile`). Remove the lockfile's line from `.gitignore` and stage it. A lockfile that was never in git shows as a new file; say so. In CI and Dockerfiles install from it: `npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable` (Yarn 1: `--frozen-lockfile`), `bun install --frozen-lockfile`, `uv sync --locked`. No lockfile at all: create one with the tool's lock command and say it is new.

   **Actions** (`check: action`). Replace `@v4` or `@main` with the full commit SHA it points to right now, and the exact version as a comment:
   - `gh api repos/<owner>/<repo>/commits/<ref> --jq .sha` gives the SHA (it follows tags for you).
   - Find the exact version for the comment: `git ls-remote --tags https://github.com/<owner>/<repo> | grep <sha>`, and take the most specific tag. Write `uses: actions/checkout@<sha> # v4.2.2`.
   - For a branch like `@main`, pin the latest release instead (`gh release view -R <owner>/<repo> --json tagName`), and say that this one changes which code runs. If there are no releases, pin main's current SHA with `# main, <today's date>`.
   - Never type a SHA from memory. If you can't look it up, leave the line and say so.

   **Images** (`check: image`). Keep the tag and add the digest the tag points to today: `docker buildx imagetools inspect <image:tag> --format '{{json .Manifest.Digest}}'` gives it (strip the quotes). Write `FROM node:20@sha256:<digest>`. No docker? Say you could not resolve it and leave the line. Say that a digest also freezes security patches, so a tool like Dependabot or Renovate should bump it.

   **Tools installed in CI** (`check: tool`). Edit only the flagged line: a blanket search-and-replace of `npm install` also hits `npm install -g`. Give `pip install x`, `npm install -g x` and `go install x@latest` an exact version: the one CI installs today if the logs show it, otherwise the current release, and say which. For `curl ... | sh`, use the tool's official setup action pinned by SHA, or a versioned download URL; if neither exists, leave it and explain the risk in one line.

   **Install scripts** (`check: scripts`). npm: add `ignore-scripts=true` to `.npmrc`. Warn that packages which compile code at install (for example `sharp`, `bcrypt`, `esbuild`) may then need `npm rebuild <name>`, and that the project's own `npm run` scripts still work. pnpm 10+ and Yarn 4 already block dependency scripts by default; only flag a setting that turns that off.

6. Run the project's install and tests once from the lockfile (`npm ci && npm test`, `uv sync --locked && uv run pytest`) if they ran before your changes. If something breaks, say what and why.
7. Report, in plain language:
   - **Found**: each problem, in a sentence.
   - **Changed**: file by file.
   - **Left alone, and why**: anything you skipped, couldn't look up, or the user declined.
   - **Security fixes**: what step 2 found, and any exception you added or proposed.
   - **When you need a new release fast**: how to exempt one package, from the table in the next section, for this project's tool and the version installed here.

## A cooldown never blocks a security fix

A cooldown also holds back the release that fixes a known hole. When the fix is younger than the wait, let that one package through by name; never switch the cooldown off.

1. Find known holes in the versions the lockfile installs. If the `cve-reachability` skill is installed, run its lookup: `python3 <skill-dir>/../cve-reachability/scripts/osv_lookup.py .`. Otherwise ask osv.dev for each package: `curl -s -X POST https://api.osv.dev/v1/query -d '{"package":{"name":"<pkg>","ecosystem":"npm"},"version":"<version>"}'` (`"PyPI"` for Python).
2. For each hole, take the fixed version (when several are listed, the lowest one on the major version installed now) and its publish date (`npm view <pkg> time --json` and read that version's entry; `time.<version>` does not work because of the dots. For Python, the PyPI release history). Count whole days from that date to today, both in UTC, and compare with the project's cooldown (or the 7 days you are adding). Holes in packages your dependencies pull in count too: report them the same way. If the parent pins the vulnerable version exactly, so upgrading the parent doesn't help, say so; an `overrides` entry (npm) or constraint (uv, Poetry) is the user's call.
3. Fix older than the cooldown: nothing blocks it. Report the hole and the fixed version; upgrading is the user's call, and this skill never upgrades on its own.
4. Fix younger than the cooldown: tell the user that the cooldown would block it, until which date, and offer to exempt that one package (ask first, as in step 4):

   | Tool | Exempt one package |
   |---|---|
   | npm 11.17+ | `min-release-age-exclude[]=<pkg>` in `.npmrc` (names only, so also pin the fixed version exactly in `package.json`). Older npm: run that one install with `--min-release-age=0`. |
   | pnpm | `minimumReleaseAgeExclude: ["<pkg>@<fixed version>"]` in `pnpm-workspace.yaml` |
   | Yarn 4 | `npmPreapprovedPackages: ["<pkg>@<fixed version>"]` in `.yarnrc.yml` |
   | bun | `minimumReleaseAgeExcludes = ["<pkg>@<fixed version>"]` in `bunfig.toml` |
   | uv | `exclude-newer-package = { <pkg> = false }` under `[tool.uv]` |
   | Poetry | `min-release-age-exclude = ["<pkg>"]` under `[solver]` in `poetry.toml` |
   | pip | no per-package exception: run that one install without `PIP_UPLOADED_PRIOR_TO` |

   Write the exception even if `warnings` says the tool here is too old: it takes effect once the tool is upgraded. Then install the fixed version exactly (`npm install <pkg>@<fixed> --save-exact` and so on). Check the lockfile diff: only that package and its own sub-packages (for example `@next/*` for `next`) may change. If the install reformatted other lines of the manifest, put them back.

   Write a comment next to the exception: the advisory id and the date the fixed version passes the cooldown. Tell the user to remove the exception after that date, so the package waits like the others again.

## Rules

- Never upgrade a version while pinning. Pinning records what is installed today.
- Never guess a SHA or digest. Look it up, or leave the line and say so.
- If the project is a library others install, don't pin its dependencies exactly in the manifest: that forces one version on every user. Pin the lockfile, CI and the cooldown instead, and tell the user why. Signs of a library: npm `package.json` without `"private": true` and with `main`, `exports` or `files`; a Python project built as a package for PyPI with no app entry point (no server, CLI or Dockerfile). If you can't tell, ask.
- `peerDependencies` stay ranges: they say what the package works with.
- The script reads only the project root, not sub-packages of a monorepo. Say so when there are more.
