---
name: handoff
description: Ends a long agent session cleanly and continues it in a fresh one. Run /handoff in a long session to save a short handoff file, type /clear, then run /handoff again to pick the work up with a small context. Use when a task is finished, the chat has grown long, or the user asks to write or continue from a handoff.
argument-hint: "[write | continue]"
---

# Handoff: end a long session, continue in a fresh one

Every message in a long chat re-reads the whole chat. A handoff moves what
matters into one short file, so the next session starts small.

## The whole flow, for the user

1. In the long session, type `/handoff`. The agent writes the handoff file.
2. Type `/clear`.
3. Type `/handoff` again. The fresh session reads the file and continues.

## Which mode to run

- `/handoff write` always writes. `/handoff continue` always continues.
- Bare `/handoff`: if this session has already done work, **write**. If the session is fresh and nothing has been done yet, **continue** from the newest file in `handoffs/`.
- If it is fresh and `handoffs/` is empty or missing, say so and ask what to work on.

## When to write one

- A task is finished and the next one is unrelated.
- The chat is getting long. Write the handoff before the tool auto-compacts the chat: a compacted summary is lossy, and a handoff you wrote on purpose keeps what matters.
- Auto-compact already fired. Treat that as a missed handoff: write one now, then start fresh instead of working on in the compacted chat.

Leave auto-compact on. It is the safety net for the times you forget.

## Write the handoff

1. Make a file in `handoffs/` at the project root, named `YYYY-MM-DD-<short-topic>.md`.
2. Keep it under about 40 lines. Facts only, no narration.
3. Use exactly these sections:

```markdown
# Handoff: <topic> (<date>)

## Done
- What was finished, with links to PRs, commits or files.

## Open
- What is still in flight: PRs, branches, background jobs, things waiting on a person.

## Next steps
1. The first concrete action for the next session.

## Key files
- path/to/file: why it matters

## Constraints
- Decisions or rules the next session must not undo.
```

4. Leave out secrets, tokens and full logs. Link to them instead.
5. Do not repeat what is already written down in specs, issues, commits or docs. Point to them by path or URL. Use paths relative to the project root, never absolute ones: the next session may run in a different directory.
6. Check the facts you write down. Run `git status` and confirm any PR or branch names you list. If there are no PRs or branches, name the commits instead.
7. Under Constraints, include every decision the user made in the chat that is not written anywhere in the repo. The next session cannot see the chat.
8. Under Next steps, list every remaining step in order, not only the first.
9. Commit the handoff file with the work, so it travels with the branch.
10. End your reply with exactly: `Handoff saved to handoffs/<file>. Type /clear, then /handoff to continue.`

If work is still mid-step, finish the step first, then write the handoff.

## Continue from a handoff

1. Read the handoff file. If there are several and none was named, use the one with the newest date.
2. Say in one line which handoff you loaded and what you will continue with.
3. Before acting, check the handoff against the repo: `git status`, `git log -5`, and the open PRs or issues it names. If anything no longer matches, say what differs, then stop and ask before doing any next step, even if the mismatch looks harmless.
4. Work through Next steps in order.
5. When every next step is done, delete the handoff file in the same commit as the work. Git history keeps it, and a leftover file would be picked up again.

## When not to write one

- A quick question with a short answer.
- A session that is still small and on the same task.
