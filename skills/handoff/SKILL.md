---
name: handoff
description: Saves a short handoff file so a long agent session can end and a fresh one can pick up the work with a small context. Use when a task is finished or the chat has grown long, or when asked to write a handoff or continue from one.
---

# Handoff: end a long session, continue in a fresh one

Every message in a long chat re-reads the whole chat. A handoff moves what
matters into one short file, so the next session starts small.

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
5. Check the facts you write down. Run `git status` and confirm any PR or branch names you list.

## Continue from a handoff

1. Start a fresh session. Clear the old chat first.
2. Point the new session at the file: "Continue from handoffs/<file>."
3. Before acting, check the handoff against the repo: `git status`, `git log -5`, and the open PRs or issues it names. If something no longer matches, say so and ask before changing it.
4. Start with the first item under Next steps.

## When not to write one

- A quick question with a short answer.
- A task that is still mid-step. Finish the step first, then write the handoff.
