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

- `/bug-to-issue investigate`, or the user describes a bug: run **Investigate**.
- `/bug-to-issue pick-up <issue number or link>`: run **Pick up**.
- If it is unclear, ask which one in one line.

## Investigate (agent 1)

Do not change any code in this mode.

1. **Restate the bug** in one or two plain sentences: what the user saw, where, and what they expected instead. If they gave steps to trigger it, keep them word for word.
2. **Reproduce it.** Make the bug happen again on purpose: run the steps, the test, or the request that shows it. Write down exactly what you ran and what came back.
   - If you cannot reproduce it, say so, say what you tried, and ask the user for the missing detail. Do not guess a cause.
3. **Inspect the code and the logs.** Logs are the program's own record of what it did. Find where it goes wrong and cite `file:line`. Separate what you saw from what you suspect.
4. **Report back, then ask.** Before proposing anything final:
   - What causes it, with the evidence.
   - The fix you would suggest, in plain words.
   - What the fix will change for users.
   - What could break, and anything else that has the same problem.
   - The questions that only the user can answer (how they want it to behave, what matters more).
   Ask those questions and wait. Explain any technical word in one line.
5. **Write the issue only after the user agrees.** Use `gh issue create` if it is available, otherwise give the user the text to paste. Use this shape:

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

6. **Stop.** Give the user the issue link and say: start a fresh session and run `/bug-to-issue pick-up <number>`. Do not start the fix yourself.

## Pick up (agent 2)

You did not write this issue. Treat it as a claim to check, not an order.

1. Read the issue, and its comments, in full.
2. **Validate it before building:**
   - Reproduce the bug yourself with the issue's steps.
   - Check that the cause it names is really where it goes wrong.
   - Check that the agreed fix would make "Done when" true, and stays inside "Not in scope".
3. If anything does not hold up, stop. Comment on the issue with what you found, and tell the user. Do not build on a wrong issue.
4. If it holds up, say so in one line, then build the fix in its own branch and pull request, link the issue, and run the "Done when" check before you call it done.

## Rules

- Never fix a bug in the same session that investigated it.
- Never say "fixed" without running the "Done when" check.
- Never invent a cause. "I could not find it" is a valid answer.
- Keep the user in charge of what the fix should do. You bring evidence and options; they decide.
