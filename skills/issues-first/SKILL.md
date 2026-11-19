---
name: issues-first
description: Every piece of work starts as a labelled GitHub issue before an agent touches code - a bug, a feature, a research experiment, or an epic that groups several. Research issues record what was tried, what it cost, what worked and what didn't, so no one pays for the same experiment twice. Use when the user reports a bug, asks for a feature, wants to try or measure something, plans something big, or asks to pick up, log to or close an issue.
argument-hint: "[new | pick-up <issue> | log <issue> | close <issue>]"
---

# Issues first: write it down, label it, then build

You are working for a builder who acts as the product manager. Before any
work starts, it lives in an issue: a numbered to-do card in the project
that stays after the chat is gone. The next agent, or the user a month
later, can see what was asked, why, and what was learned.

Write for someone who may not code: plain words, and explain any technical
word in one line the first time you use it.

## Where issues live

- If `gh` works in this project (`gh repo view` succeeds), use GitHub issues.
- Otherwise use an `issues/` folder: one file per issue, `issues/<number>-<short-topic>.md`, where the number is the highest existing one plus 1. Line 1 holds the labels (`labels: research`), line 2 the state (`state: open`). The file number is the issue number, so `#3` means `issues/3-...`. To close it, change line 2 to `state: closed`.

First time in a project on GitHub, make sure the four labels exist (`gh label create <name> --force`). In the `issues/` folder there is nothing to create: the label is just written on line 1.

| Label | For |
|---|---|
| `bug` | Something that worked, or should work, and doesn't. |
| `feature` | Something new, or a change to how something works. |
| `research` | An experiment: trying, measuring or comparing something to learn whether it is worth doing. |
| `epic` | A big goal split into several issues. |

## Which mode to run

- `/issues-first` or `new`, or the user describes work: run **New**.
- `pick-up <issue>`: run **Pick up**.
- `log <issue>`: run **Log a research run**.
- `close <issue>`: run **Close**.
- If it is unclear, ask in one line.

## Always first: search what exists (cheaply)

Searching costs tokens too, so keep it narrow: filter by label, read titles
first, and open only what matches.

- **Before an experiment** (`research`): search only `research` issues, open and closed, by title: `gh issue list --label research --state all --search "<2-3 words> in:title" --limit 10 --json number,title,state`. In the `issues/` folder: `grep -l "labels:.*research" issues/*.md`, then match the file names.
- **Before a bug or feature**: search only open issues with that label, the same way, to avoid a duplicate.
- Open at most 3 matches. For a research issue, read only "What didn't work", "Verdict" and "Retry when", not the whole thread.
- Skip the search for a small fix the user has already described in full.

Then:

- If an issue already covers it, say so with its number and use that one.
- If a research issue already tried it, tell the user what was found and what it cost, and whether its "Retry when" condition has changed. If the user says it hasn't, stop and file nothing.

## New

Do not change the project's files in this mode, except the `issues/` folder.

1. **Pick the label** and say which in one line. Something broken -> `bug`. Something new -> `feature`. "I want to try / see if / measure / compare" -> `research`. Work that needs more than about a day, or several separate parts -> `epic`.
2. **Read the project** for what this touches, and cite `file:line`.
3. **Ask, don't assume.** Numbered questions, at most five per round, most important first, each with your best guess so the user can just say "yes". Ask only what the project can't tell you. Repeat until nothing important is open.
4. **Show the draft and ask "OK to file this?"** File it only after a yes. No open questions go into an issue.
5. **Stop.** Give the number and say: start a fresh session and run `/issues-first pick-up <number>`. Do not start the work in this session.

### Bug

Reproduce it first, and write down exactly what you ran and what came back.
If you can't reproduce it, say so and ask for the missing detail. Never
guess a cause.

```markdown
## What happens
What the user saw, and what they expected.
## How to reproduce
1. Exact steps or command. Result: what came back.
## Cause
What goes wrong, with file:line. Mark what is confirmed and what is suspected.
## Agreed fix
## Done when
- A check that fails today and passes once fixed (usually a new test).
## Not in scope
```

### Feature

```markdown
## What and why
Who it is for, what they can do once it ships, and why it matters.
## How it should work
1. Step by step, from the user's side.
## Awkward cases
- Empty, too many, wrong input, no permission, fails halfway: what should happen.
## What exists today
With file:line.
## Done when
- Checks anyone can run (a test, a command, a page and what it shows).
## Not in scope
```

### Research

Agree the question and the limits before anything runs.

```markdown
## Question
One question this experiment answers, e.g. "Does caching X make the tests faster?"
## Why it matters
What we do differently depending on the answer.
## Before this
Related research issues and what they found, or "none found".
## Plan
What to run, on what, how many times, and how the result is measured.
## Budget
The most it may spend in money, tokens and time. Stop at the limit.
## Success looks like
The result that would make us adopt it, decided before running.
## Runs
| Date | What changed | Result | Cost | Notes |
|---|---|---|---|---|
## What worked
## What didn't work
## Verdict
Adopt / drop / inconclusive, and why.
## Retry when
The condition that would make it worth trying again (a new tool, a cheaper model, a bigger data set), or "never".
```

The last five sections stay empty until there are runs.

### Epic

```markdown
## Goal
What is true when the whole thing is done.
## Parts
- [ ] #<n> first part
- [ ] #<n> second part
## Order
What must come first, and what can run at the same time.
## Done when
```

File the epic, then file each part as its own `bug`, `feature` or `research`
issue whose first line is `Part of #<epic>`, and tick the epic's list as
each part closes. Each part goes through the same questions as above, and
each part is small enough for one session.

## Pick up

You did not write this issue. Treat it as a plan to check, not an order.

1. Read the issue and its comments in full, and the epic it is part of, if any.
2. **Check it before working.** Is "What exists today" or "Cause" still true in the code? Is any step unclear, any awkward case missing, any "Done when" uncheckable, any part contradicting "Not in scope"? For a bug, reproduce it yourself. For research, re-check "Before this" for runs added since.
3. If something does not hold up, stop. Comment on the issue with what you found and the questions it raises, and tell the user. Do not fill a gap with your own guess. Small slips (a moved line number) don't stop the work: note them and carry on.
4. If it holds up, comment that it checked out, then work in its own branch and pull request that names the issue. For `bug` and `feature`, write the "Done when" checks first and confirm they fail, then build until they pass. For `research`, follow **Log a research run** for every run.

## Log a research run

After **every** run, before the next one, and even when it failed:

1. Add a row to "Runs": the date, what changed from the last run, the result in numbers, and the cost (money, tokens, time).
2. Add one line to "What worked" or "What didn't work", in plain words with the number. A failed run is a finding, not a waste. Write it down.
3. Check the budget. At or past it, stop and ask the user.

Write the log as you go, not at the end: a session can end at any time,
and an unlogged run is a run someone will pay for again.

## Close

- `bug` and `feature`: only after the "Done when" checks pass. Comment with the results and the pull request.
- `research`: only after "Verdict" and "Retry when" are filled in. A dropped idea gets closed with its reasons, never deleted, because the closed issue is what stops the next person from repeating it.
- `epic`: only when every part is closed.

## Rules

- No work without an issue, and no issue without a label.
- Search before writing a new issue: by label and title, and never by reading every issue.
- Never do the work in the same session that wrote the issue.
- Never say "done" without running the "Done when" checks.
- Never run an experiment without a question, a budget and a "success looks like".
- Every research run gets logged, including the ones that failed.
- Keep the user in charge. You bring evidence and questions; they decide.
