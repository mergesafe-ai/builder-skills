---
name: keep-secrets-from-agents
description: Keeps a project's secrets out of a coding agent's reach. Finds .env files, private keys and credential files, checks they are gitignored and that Claude Code, Cursor and other agents are blocked from reading them or printing the environment, finds agent instructions (AGENTS.md, CLAUDE.md, rules, skills) that point the agent at .env, and gives the agent its own task-scoped token instead of the shared .env. Use when asked to keep an agent away from .env, secrets or credentials, or to stop Claude from reading them; when setting up a project for coding agents, or before writing or editing AGENTS.md, CLAUDE.md, GEMINI.md, Cursor rules or Copilot instructions, so they never send the agent to a secret; and when adding an API key, token or other secret to a project. Pinning dependencies is pin-and-cooldown; known vulnerabilities are cve-reachability.
---

# Keep secrets out of your coding agent's reach

In November 2026, NordLayer's AI Scout research described a coding agent asked
to review merge requests. The project's instructions pointed it to a GitLab
token kept in `.env`. That file also held production passwords for an internal
admin tool, an HR system API token and a BI client secret. Over 10 sessions in
3 weeks the agent loaded the whole file each time, so every secret in it ended
up in the session's output. When `.env` was missing, the command returned the
entire shell environment instead.

Four things let that happen, and this skill checks each one:

- **A secret file the agent could read**, with no rule telling the agent's tool to block it.
- **An instruction file that sent the agent there** ("use the token in `.env`").
- **One file mixing the agent's token with production secrets**, so reading one meant reading all.
- **Nothing stopping the agent from printing the environment** (`env`, `printenv`).

Words used below:

- **Deny rule / ignore file**: a setting that tells one agent tool not to read a file. Each tool has its own.
- **Task-scoped token**: a token made only for the agent's job, with the fewest permissions it needs (for example, a GitLab project access token or a GitHub fine-grained token limited to one repository), ideally with an expiry date.
- **Run-time injector**: a tool that puts a secret into one command's environment when it runs, so the secret never sits in a project file (for example a password manager's CLI, such as 1Password's `op run`, or a secrets service's CLI, such as `doppler run`, or your hosting platform's secret store).

## You never see a secret

- Never open, `cat`, `grep`, `head`, `source` or print a secret file, and never run `env`, `printenv` or `echo $SOME_TOKEN`. The script tells you file names and key names; that is all you need.
- Never ask the user to paste a secret into the chat. The user creates, moves and rotates secrets themselves; you change files that refer to secrets by name.
- Don't edit secret files yourself. Once your deny rules are in place you can't read them anyway (Claude Code applies them to `sed` too), and that is the point. The user removes or blanks lines in their own `.env`. The one exception is a template (`.env.example`) holding real values: see step 7.

## Two ways in

- **The user asked** to keep agents away from secrets, or **you are setting a project up for coding agents** (writing `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, Cursor rules): do the whole check below.
- **You are adding an API key, token or secret** for a new integration: do only this part.
  1. Read it in code from an environment variable (`process.env.STRIPE_API_KEY`, `os.environ["STRIPE_API_KEY"]`).
  2. Add the key name with an empty or placeholder value to the template (`.env.example`), never a real value.
  3. Run the script (step 1 below) and fix only the `not_ignored`, `tracked` and `claude_read` findings for the secret file the key will live in, after asking.
  4. Tell the user to put the real value in their `.env` or secret store themselves, and to use a key with only the permissions this integration needs. Mention in one line that this skill can check the rest of the project.

## Steps (whole check)

1. From the project root, run `python3 <skill-dir>/scripts/check_secrets.py .`
   It prints JSON: the secret files it found (with key names, never values), whether each is in git and gitignored, what each agent tool blocks, and a list of `findings`. It reads files but changes nothing and uses no network.
2. If `findings` is empty, tell the user the project's own files already cover it: name the checks that passed (secret files gitignored and untracked, Claude Code deny rules cover them and block `env` and `printenv`, any other tool found, no instruction points at a secret), suggest the shell variable from step 4 (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`), pass on the limits in "What this can't stop", and stop. Change nothing.
3. Otherwise, show the user the list of changes you would make, grouped by finding, in plain language. **Ask before changing anything**, unless the user already said to just do it. Even then, always ask before touching a secret file itself, and remind them that rotating or moving secrets is theirs to do.
4. **Block agent reads**, per tool. Only these mechanisms are documented; don't invent others.

   **Claude Code** (`claude_read`, `claude_env_dump`, `claude_read_local_only`, `claudeignore`, `claude_settings_invalid`). Add rules to `permissions.deny` in the shared `.claude/settings.json` (commit it so everyone who clones gets them). Keep every rule already there; settings files are strict JSON.

   ```json
   {
     "permissions": {
       "deny": [
         "Read(.env)",
         "Read(.env.*)",
         "Read(!.env.example)",
         "Bash(env)",
         "Bash(printenv *)"
       ]
     }
   }
   ```

   - Add one `Read(...)` rule per kind of secret file the script found: `Read(*.pem)`, `Read(*.key)`, `Read(id_rsa)`, `Read(credentials.json)`, `Read(.npmrc)`. A bare file name or `*.ext` matches at any depth.
   - `Read(!.env.example)` must come after `Read(.env.*)`: it carves the template back out. Add one per template the project has (`.env.sample`, `.env.template`), and none if there is none.
   - Read deny rules also cover the file commands Claude Code recognises in Bash, such as `cat`, `head`, `tail` and `sed`, so you don't need `Bash(cat .env)`.
   - `Bash(printenv *)` also blocks a bare `printenv`.
   - A `.claudeignore` file has no effect: move its entries into `Read(...)` rules and tell the user it can be deleted.
   - Also suggest, for the user's shell: `export CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` before starting Claude Code. It strips credentials (recognised by variable name or value shape) from the environment of Bash commands, hooks and MCP servers that Claude Code starts.

   Docs: https://code.claude.com/docs/en/permissions, https://code.claude.com/docs/en/env-vars

   **Cursor** (`cursor_read`). Cursor already ignores `.env*` files and everything in `.gitignore`. For other secret files, add their patterns to `.cursorignore` in the project root (gitignore syntax), and remove any `!` line that re-includes a secret file. Tell the user that Cursor says the agent's terminal and MCP tools can still reach these files. Docs: https://cursor.com/docs/context/ignore-files

   **Gemini CLI** (`gemini_read`). Add the patterns to `.geminiignore` in the project root (gitignore syntax) and restart Gemini CLI. Its docs say tools "that support this feature" skip those files, without listing which; they don't say it covers shell commands. Docs: https://geminicli.com/docs/cli/gemini-ignore/

   **Codex** (`codex_read`). Codex's documented mechanism is a permission profile (marked beta) that denies paths to its sandboxed commands. The docs show it in `~/.codex/config.toml`; suggest the user add it there:

   ```toml
   default_permissions = "project-edit"

   [permissions.project-edit]
   extends = ":workspace"

   [permissions.project-edit.filesystem.":workspace_roots"]
   "**/*.env" = "deny"
   "**/.env" = "deny"
   ```

   Warn that if `sandbox_mode` appears in any loaded config file, Codex uses that older setting instead of `default_permissions`. To keep variables whose names contain `KEY`, `SECRET` or `TOKEN` out of commands Codex runs, add `ignore_default_excludes = false` under `[shell_environment_policy]`. Docs: https://learn.chatgpt.com/docs/permissions, https://learn.chatgpt.com/docs/config-file/config-advanced

   **GitHub Copilot** (`agent_tools.copilot`). There is no file in the repo for this. Content exclusion is set on GitHub under the repository's **Settings > Copilot > Content exclusion**, for repositories owned by an organization on Copilot Business or Enterprise. Tell the user where it is; you can't check it. Docs: https://docs.github.com/en/copilot/concepts/context/content-exclusion

   **Any other tool**: say you found no documented project-level setting for it. Don't make one up.

5. **Fix instructions that point at secrets** (`instruction_points_at_secret`, `instruction_reads_secret`, `instruction_dumps_env`, `secret_in_instructions`). This is how the NordLayer leak started.
   - Ask the user what the agent actually needs (for example: "post review comments on merge requests in this one project").
   - Ask them to create a **task-scoped token** for exactly that, and to keep it out of the project: an environment variable they set before starting the agent, or a run-time injector wrapping the one command that needs it. You don't create the token.
   - Rewrite the line to name the variable, not a file, and to forbid reading secret files, for example: `To call the GitLab API, use the GITLAB_REVIEW_TOKEN environment variable. Never read .env or print environment variables.` Remove any line telling the agent to fall back to `env`, `printenv` or the shell environment.
   - `secret_in_instructions`: a token is written in the instruction file itself. Remove that line without printing it (use the line number), and tell the user to rotate that token now.
   - Check skills, commands and rules files the script lists too, not only `AGENTS.md`.

6. **Split mixed secret files** (`mixed_secret_file`). The agent's token and production secrets should never share a file the agent may be sent to.
   - Tell the user which key names are in the file and which one the agent's task uses.
   - Recommend they move the others out of the project: into a secret manager or run-time injector, or the deploy platform's secret store. Production secrets are safest not on the machine where an agent runs at all.
   - Offer to change code or scripts that load them to read the same variable names from the environment. The user deletes the moved lines from `.env` once they have moved them.

7. **Git** (`not_ignored`, `tracked`, `in_history`, `template_has_values`).
   - `not_ignored`: add the pattern the finding gives to `.gitignore` (keep `!.env.example` if the template should stay committed).
   - `tracked`: `git rm --cached <file>` (the file stays on disk) and gitignore it. Tell the user plainly: **every secret in it must be rotated**; removing it from git does not undo the exposure. Rewriting history is their call and does not replace rotating.
   - `in_history`: the file was committed before. Same message: rotate.
   - `template_has_values`: a template holds real-looking values. Blank each value by key name without printing it (`sed -i.bak 's/^HR_API_TOKEN=.*/HR_API_TOKEN=/' .env.example`, then delete the `.bak` file), and if the template is in git, say those secrets must be rotated.

8. Re-run the script and check that the findings you fixed are gone. Findings that wait on the user stay until they act: `mixed_secret_file` until they move the other secrets out, and `in_history` for good (it is a reminder to rotate). List those under "For you to do"; they don't mean your changes failed. Validate `.claude/settings.json` with `python3 -m json.tool .claude/settings.json > /dev/null`.
9. Report, in plain language:
   - **Found**: each problem, in a sentence.
   - **Changed**: file by file.
   - **For you to do**: tokens to create, secrets to move, secrets to rotate (name each key), settings only they can change (Copilot, user-level Codex config, the shell variable).
   - **What this can't stop**: the section below, in two or three lines.

## What this can't stop

Say this to the user; don't overstate what the rules do.

- **Deny and ignore rules are guardrails, not a sandbox.** They stop an agent's own file tools and the commands it usually writes. An agent with a general shell can still find other ways: a Python or Node script that opens the file, `grep -r` over the folder, `sh -c 'env'`, a full path to the program. Claude Code's docs say so for Read and Bash rules; Cursor's say the terminal and MCP tools aren't covered; Copilot's say content exclusion is not a security boundary.
- **Secrets already in the shell environment** reach every command the agent runs unless the tool strips them (Claude Code's `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`, Codex's `shell_environment_policy`).
- **What holds**: run the agent where production credentials don't exist (a container, VM or the tool's OS-level sandbox, such as Claude Code's `sandbox` settings with `filesystem.denyRead`), and give it only a task-scoped, short-lived token.
- The script reads the project only, not user-level or managed settings, and it does not scan source code for hard-coded secrets.

## Rules

- Never read, print or ask for a secret value. Key names only.
- Never weaken an existing deny rule, ignore line or `.gitignore` entry.
- Never create, rotate or move a secret yourself; tell the user exactly which ones.
- A line in an instruction file that only mentions `.env` for humans (for example "copy `.env.example` to `.env`") is fine. Judge each hit: fix lines that send the agent to a secret, leave documentation.
