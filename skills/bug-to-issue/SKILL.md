---
name: bug-to-issue
description: Turns "I found a bug" into a checked GitHub issue before anyone fixes anything. One agent reproduces the bug, inspects the code and logs, explains what a fix would change and what could break, and writes the issue once the user agrees. A different agent then picks the issue up and validates it before building. Use when the user reports a bug, says something is broken, or asks to pick up a bug issue.
argument-hint: "[investigate | pick-up <issue>]"
---

# Bug to issue: investigate first, fix second, with two agents

You are working for a builder who acts as the product manager. Your job is
to turn what they saw into clear requirements, not to jump to a fix.

"Fix it" is the prompt this skill replaces. The agent that investigates a
bug does not fix it. It writes an issue, and a second agent, in a fresh
session, checks that issue before building anything.

## Which mode to run

- `/bug-to-issue` or `/bug-to-issue investigate` with a bug description, or the user just describes a bug: run **Investigate**.
- `/bug-to-issue pick-up <issue number or link>`: run **Pick up**.
- If it is unclear, ask which one in one line.

Write for someone who may not code: plain words, and explain any technical
word in one line the first time you use it.

## Investigate (agent 1)

Do not change the project's files in this mode. Throwaway scripts to
reproduce or probe the bug are fine; delete them when you are done.

1. **Restate the bug** in one or two plain sentences: what the user saw, where, and what they expected instead. If they gave steps to trigger it, keep them word for word.
2. **Reproduce it.** Make the bug happen again on purpose: run the steps, the test, or the request that shows it. Write down exactly what you ran and what came back.
   - If you cannot reproduce it, say so, say what you tried, and ask the user for the missing detail. Do not guess a cause.
3. **Inspect the code and the logs.** Logs are the program's own record of what it did. Find where it goes wrong and cite `file:line`. Separate what you saw from what you suspect.
   - If part of the cause is outside what you can see (another service, the user's browser, a caller not in this repo), say which part is confirmed and which part is still unknown.
4. **Report back, then ask.** Keep it short, in this order:
   - **Cause:** what goes wrong, with the evidence.
   - **Suggested fix:** in plain words.
   - **What changes for users.**
   - **What could break**, and anything else with the same problem. Flag data the bug may already have affected (past orders, saved records), but do not go and change it.
   - **Questions only you can answer:** how it should behave, what matters more. Number them.
   Then stop and wait for the answers.
5. **Write the issue only after the user agrees.** Show them the draft first and ask "OK to file this?" Then use `gh issue create` if it is available; otherwise save it as `issues/<short-topic>.md` in the project and tell the user where it is. "Done when" must include at least one check that **fails today and will pass once fixed**, usually a new test that reproduces the bug. Checks that already pass and only guard against breaking something else are fine, but mark them "(guard)". Use this shape:

```markdown
## What happens
What the user saw, and what they expected.

## How to reproduce
1. Exact steps or command.
Result: what came back.

## Cause
What goes wrong, with file:line and the log lines that show it.

## Agreed fix
What to change, as the user approved it.

## What could break
Risks, and other places with the same problem.

## Done when
- A check anyone can run that proves it is fixed (a test, a command, a page to open).

## Not in scope
- What the fix must not touch.
```

6. **Stop.** Give the user the issue link (or the file path) and say: start a fresh session and run `/bug-to-issue pick-up <number, link or file path>`. Do not start the fix yourself.

## Pick up (agent 2)

You did not write this issue. Treat it as a claim to check, not an order.

1. Read the issue, and its comments, in full.
2. **Validate it before building.** Throwaway scripts are fine here too.
   - Reproduce the bug yourself with the issue's steps. If the steps don't give the claimed result, look in the logs for what really triggers it.
   - Check that the cause it names is really where it goes wrong.
   - Write the "Done when" tests first and run them. At least one must **fail** before the fix; checks marked "(guard)" may pass. If none fails, the issue cannot prove anything.
   - Check that the agreed fix would make "Done when" pass, and stays inside "Not in scope".
3. If anything does not hold up, stop. Comment on the issue with what you found (with `gh issue comment`, or give the user the text), and tell the user in plain words. Say that the fix they approved rests on that finding, and suggest running `/bug-to-issue` again to re-investigate. Do not build on a wrong issue.
   - Small slips (a line number that moved, a typo in a step) don't stop the work: note them in your comment and carry on.
4. If it holds up, comment on the issue that it checked out, then build the fix in its own branch and pull request that names the issue, and run the "Done when" checks before you call it done.
5. **Report back** in this order: what you checked and what you found, what you changed, the "Done when" results before and after, and what you left alone because it was out of scope.

## Rules

- Never fix a bug in the same session that investigated it.
- Never say "fixed" without running the "Done when" check.
- Never invent a cause. "I could not find it" is a valid answer.
- Keep the user in charge of what the fix should do. You bring evidence and options; they decide.
