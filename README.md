# Builder skills

Free skills for people building with AI coding agents. Each one is small,
does one job, and comes with a way to check it on your own work.

## What you get

**End a long session cleanly** (`handoff`)

- Saves what got done, what's open and the next step in one short file.
- A fresh session picks it up without re-reading the whole old chat, which is where most agent token spend goes.
- Each handoff gets a short id, so `/handoff ec84ca` loads that exact one, even pasted with a stray `#` or dot, or with one character wrong.
- Lists the subagents still running, so the next session messages them instead of starting the same work twice. When no work is left, it asks whether to close the session instead of writing an empty handoff.
- Comes with a script that reads your local Claude Code logs and estimates what handoffs would save you. Nothing leaves your machine.

**Turn a bug into a checked issue** (`bug-to-issue`)

- Instead of "fix it": the agent reproduces the bug, inspects the code and the logs, and tells you what a fix would change and what could break.
- Once you agree, it writes a GitHub issue and stops.
- A second agent, in a fresh session, picks the issue up and checks it before building anything.

**Put every piece of work in a labelled issue** (`issues-first`)

- Every bug, feature, experiment and big goal becomes a GitHub issue, labelled `bug`, `feature`, `research` or `epic`, before an agent touches code.
- Research issues record the question, the budget, every run and what it cost, what worked, what didn't, and when it is worth retrying.
- One pinned `Research index` issue lists every experiment with its verdict and when to retry. Before an experiment, the agent reads that one issue, not all of them, so it won't pay for one that already failed. Searching costs tokens too.

**Check your dependencies** (`cve-reachability`)

- Lists every library your app pins, and flags the ones with a known security hole.
- For each one: what the hole lets someone do, the version that fixes it, and how long it has been public.
- Looks through your code and says whether you use the broken part. If it can't tell, it says that too.

## Install the handoff skill (Claude Code)

```bash
git clone https://github.com/mergesafe-ai/builder-skills
mkdir -p ~/.claude/skills
cp -r builder-skills/skills/handoff ~/.claude/skills/handoff
```

Start a new Claude Code session, and the `/handoff` command is there. The whole flow is three steps:

1. In a long session, type `/handoff`. Claude writes a short handoff file in `handoffs/` in your project and tells you its id.
2. Type `/clear`.
3. Type `/handoff` again (or `/handoff <id>` for a specific one). The fresh session reads the file, checks it against your repo, and continues.

**Optional reminder.** To have Claude tell you when a session has grown large enough to hand off, add this hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/skills/handoff/hooks/handoff_hint.py" } ] }
    ]
  }
}
```

It shows a one-line note once the session passes 300,000 tokens of context (set `HANDOFF_HINT_FIRST` in the `env` block to change it, e.g. `"150000"`), and again every 100,000 more. It also shows one when you come back after an hour or more to a session of 80,000+ tokens: the prompt cache has expired by then, so your next message re-sends the whole context, which makes it the cheapest moment to start fresh. It never blocks a message.

**Keep handoffs out of the repo.** By default handoffs go in `handoffs/` in your project, ready to commit. To keep them private instead, set `HANDOFF_DIR` (for example in the `env` block of `~/.claude/settings.json`). `{repo}` is replaced with the repo's folder name, and every worktree of a repo shares one folder:

```json
{ "env": { "HANDOFF_DIR": "~/.claude/handoffs/{repo}" } }
```

**Measure first.** See what handoffs would save on your own sessions:

```bash
python3 ~/.claude/skills/handoff/scripts/measure.py
```

## Install the bug-to-issue skill (Claude Code)

```bash
git clone https://github.com/mergesafe-ai/builder-skills
mkdir -p ~/.claude/skills
cp -r builder-skills/skills/bug-to-issue ~/.claude/skills/bug-to-issue
```

1. Found a bug? Type `/bug-to-issue` and describe what you saw. The agent investigates, asks you how you want it fixed, then writes the issue.
2. Type `/clear` (or open a new session).
3. Type `/bug-to-issue pick-up <issue number>`. The new agent checks the issue, then builds the fix.

**Using Cursor, Codex or another agent?** The skill is one plain-text file. Copy `skills/bug-to-issue/SKILL.md` into your project and tell your agent: "When I report a bug, follow SKILL.md in investigate mode. When I give you an issue to fix, follow it in pick-up mode."

## Install the issues-first skill (Claude Code)

```bash
git clone https://github.com/mergesafe-ai/builder-skills
mkdir -p ~/.claude/skills
cp -r builder-skills/skills/issues-first ~/.claude/skills/issues-first
```

1. Start a new Claude Code session so the skill loads. Describe a bug, a feature, something you want to try, or a big goal, and type `/issues-first`. The agent searches what exists, asks you questions, shows the draft and files the issue once you say OK.
2. Type `/clear` (or open a new session).
3. Type `/issues-first pick-up <issue number>`. The new agent checks the issue, then does the work. For an experiment it logs every run and its cost as it goes.
4. `/issues-first close <issue number>` closes it once the checks pass, or once an experiment has a verdict.

No GitHub? The skill keeps the issues as files in an `issues/` folder instead.

**Optional gate.** The skill asks the agent to file an issue first; an agent that skips the skill can still edit code. To make the rule hold, add this hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|Skill",
        "hooks": [ { "type": "command", "command": "python3 ~/.claude/skills/issues-first/hooks/issue_gate.py" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "python3 ~/.claude/skills/issues-first/hooks/issue_gate.py" } ] }
    ]
  }
}
```

In a git repo, it then blocks file edits, `git commit` and `git push` until one of these is true:

- the branch names an issue: `issue-12`, `12-topic` or `#12`;
- this session picked an issue up (`/issues-first pick-up 12` or `/bug-to-issue pick-up 12`);
- you typed `no-issue: <reason>` in this session, for a change that needs no issue. Only you can type it, so the agent can't exempt itself.

Files outside a git repo, and in `issues/`, `.claude/` or `handoffs/`, are never blocked. If the hook itself fails, the edit goes through. Every block, pick-up and exemption is written to `~/.claude/skill-log.jsonl`; see where the gate got in your way with:

```bash
python3 builder-skills/scripts/skill_report.py --days 7
```

**Using Cursor, Codex or another agent?** Copy `skills/issues-first/SKILL.md` into your project and tell your agent: "Before any work, follow SKILL.md."

## Check your dependencies on your app

You need Python 3.11+ and internet access. No account, no API key, no installs.

```bash
git clone https://github.com/mergesafe-ai/builder-skills
python3 builder-skills/skills/cve-reachability/scripts/osv_lookup.py /path/to/your/app
```

Or give the `cve-reachability` folder to Claude Code, and ask it to check your app for known security holes.

## What it reads, and what it doesn't

- Reads Python (`uv.lock`) and npm (`package-lock.json`) projects. Other languages are not covered yet.
- Asks osv.dev (a free, public vulnerability database) about each exact version you have. Your code is not uploaded anywhere.
- A clean result doesn't mean your app is secure. It means no known hole matched the libraries you pinned.

## Contributing

Every new or changed skill is measured before it merges: which prompts load it, which don't, and a run end to end. See [AGENTS.md](AGENTS.md).

## License

MIT. Use it, fork it, and send fixes.
