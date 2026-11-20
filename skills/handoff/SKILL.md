---
name: handoff
description: Ends a long agent session cleanly and continues it in a fresh one. Run /handoff in a long session to save a short handoff file, type /clear, then run /handoff again to pick the work up with a small context. Use when a task is finished, the chat has grown long, or the user asks to write or continue from a handoff, including one named by its short id.
argument-hint: "[write | continue | <id>]"
---

# Handoff: end a long session, continue in a fresh one

Every message in a long chat re-reads the whole chat. A handoff moves what
matters into one short file, so the next session starts small.

## The whole flow, for the user

1. In the long session, type `/handoff`. The agent writes the handoff file and gives it a short id, like `ec84ca`.
2. Type `/clear`.
3. Type `/handoff` again (or `/handoff ec84ca` for that exact one, in any session). The fresh session reads the file and continues.

The script `scripts/handoff.py`, in this skill's folder, names new handoffs and finds them by id. Run it from the project root.

## Which mode to run

- `/handoff write` always writes. `/handoff continue` always continues.
- `/handoff <id>`: **continue** from that handoff. Anything that is not `write` or `continue` is an id, even with a stray `#`, dot or comma around it.
- Bare `/handoff`: if this session has already done work, **write**. If the session is fresh and nothing has been done yet, **continue** from the newest file in `handoffs/`.
- If it is fresh and `handoffs/` is empty or missing, say so and ask what to work on.

## When to write one

- A task is finished and the next one is unrelated.
- The chat is getting long. Write the handoff before the tool auto-compacts the chat: a compacted summary is lossy, and a handoff you wrote on purpose keeps what matters.
- Auto-compact already fired. Treat that as a missed handoff: write one now, then start fresh instead of working on in the compacted chat.

Leave auto-compact on. It is the safety net for the times you forget.

## When no work is left, close out instead

If nothing is in flight and no next step is left for a next session (only
waits on outside replies, or optional ideas), do not write a handoff. Say
there is no work left, list anything still waiting on someone else, and ask
the user whether to close the session. An empty handoff would just be loaded
and acted on by the next session.

## Write the handoff

1. Get the file name: `python3 <skill-dir>/scripts/handoff.py new <short-topic>`. It prints `handoffs/<id>-<short-topic>.md` with a free 6-character id. Write the handoff there.
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

## Subagents
| Agent id | Working on | Worktree or branch | Current step |
|---|---|---|---|
| (from your agent list) | issue, PR or task | path or branch | what it is doing |

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
9. Under Subagents, list every subagent or background agent still running, with the id you would message it by. They keep running after `/clear`, and the next session can message them instead of starting the same work twice. Write `None running.` if there are none.
10. Commit the handoff file with the work, so it travels with the branch.
11. End your reply with exactly: `Handoff <id> saved to handoffs/<file>. Type /clear, then /handoff to continue (or /handoff <id> in any session).`

If work is still mid-step, finish the step first, then write the handoff.

## Continue from a handoff

1. Run `python3 <skill-dir>/scripts/handoff.py find [<id>]` and read what it prints. With no id it prints the newest handoff. If it says it loaded a close match instead of the id typed, repeat that line to the user. If it prints `NO HANDOFF FOUND` or `NO HANDOFF LOADED`, show the user what it printed and ask which to use; do not pick one yourself.
2. Say in one line which handoff you loaded and what you will continue with.
3. Before acting, check the handoff against the repo: `git status`, `git log -5`, and the open PRs or issues it names. If anything no longer matches, say what differs, then stop and ask before doing any next step, even if the mismatch looks harmless.
4. Before starting any agent, list the agents already running and match them to the Subagents table. Message a running one about its task instead of starting a new agent for the same work.
5. Work through Next steps in order.
6. When every next step is done, delete the handoff file in the same commit as the work. Git history keeps it, and a leftover file would be picked up again.

## When not to write one

- A quick question with a short answer.
- A session that is still small and on the same task.
