---
name: count-before-you-cut
description: Before applying any trick meant to save tokens or AI cost (shorter variable names, minified code or prompts, stripped comments, trimmed context, a different file format), measure it for free on a real sample from this project, apply it only if it saves enough, and record the verdict so nobody measures it twice. Use when the user or the agent proposes changing code, prompts or files to make them cheaper or smaller for an AI model. Not for ordinary edits, refactors or renames made for other reasons.
argument-hint: "[<the trick to check>]"
---

# Count before you cut: measure a token-saving trick before using it

You are working for a builder who acts as the product manager. Many
"save tokens" tricks sound obvious and do nothing, or make things worse.
Counting tokens on your own files is free, so count first. Write in plain
words, and explain any technical word in one line.

A **token** is the small chunk of text an AI model reads and bills by.
A **tokenizer** is the tool that splits text into tokens.

## Why: a trick that sounded right and wasn't

On 33 real pull requests, renaming identifiers (the names of variables and
functions) to short aliases **raised** the token count:

- Initials (`this_variable` -> `t_v`): **+0.4%**.
- Shortest aliases (`v12`): **+2.6%**.

The reason: tokenizers store common English words as single tokens.
`organization_context` is 2 tokens (`organization`, `_context`), and `o_c`
is also 2 tokens (`o`, `_c`), counted with o200k_base. The short name saves
nothing and is much harder to read. Your files may differ, which is why
you count.

## When to run

Run this before the change, whenever the stated reason for it is fewer
tokens or a lower AI bill. Examples: "shorten the variable names to save
tokens", "minify the prompt", "strip comments so the agent reads less",
"send YAML instead of JSON, it's cheaper".

Do not run it for a typo fix, a bug fix, a feature, or a rename done for
clarity. Just do that work.

## 1. Check the research index first

This skill uses the research index from the `issues-first` skill: one
pinned issue titled `Research index` (or `issues/0-research-index.md`). Read
it the way `issues-first` says, and nothing more.

- If a row covers the same trick (the same idea, even worded differently),
  tell the user its verdict, numbers and "Retry when". If you are not sure
  it is the same trick, ask in one line. If the "Retry when" has not come
  true, **stop**. Do not measure again, do not apply the trick, and add
  nothing to the record.
- If no row matches, say so in one line and continue.

## 2. Measure for free, on real files

Nothing here calls an AI model, so it costs $0. Count on copies outside
the project, and delete them when done.

1. **Take a real sample from this project**, never made-up examples: the
   20-30 files the agent reads most, copied to a folder outside the
   project, for example `/tmp/cbyc/before/`. Fewer files in the project?
   Use them all, and say the sample is small.
2. **Pin down the trick.** If the user named a form, measure only that
   one. If they left it open ("shorter names"), measure each common form separately,
   for example `t_v`, `tv` and `v12`, and report each one.
3. **Apply it to a copy** in `/tmp/cbyc/after/` (one folder per form),
   the same way to every file, and only where it applies (a rename touches only names
   the project defines, not text inside strings or comments).
   Write a small throwaway script for this. Never edit the project here.
4. **Count tokens before and after** with a real tokenizer:

```bash
uv run --with tiktoken python - /tmp/cbyc/before /tmp/cbyc/after <<'EOF'
import sys, pathlib, tiktoken
enc = tiktoken.get_encoding("o200k_base")
def count(d):
    return sum(len(enc.encode(p.read_text(errors="ignore"), disallowed_special=()))
               for p in pathlib.Path(d).rglob("*") if p.is_file())
b, a = count(sys.argv[1]), count(sys.argv[2])
print(f"o200k_base: before {b}, after {a}, change {(a - b) / b:+.1%}")
EOF
```

No `uv`? Run `pip install tiktoken`, then the same script with `python3 -`.

Always name the tokenizer in the result. `o200k_base` is the one OpenAI's
recent models use. Other models (Claude, Gemini, open models) split text
differently, so treat the number as a good estimate, not an exact bill. If
the model's maker offers a free token-count tool, check with it too.

## 3. Decide

- **Threshold:** the trick must save at least **5%** of all tokens in the
  sample, unless the user set a different bar before measuring.
- **Below the threshold, or more tokens:** do not apply it. Tell the user
  the numbers in one or two lines.
- **At or above it:** show the user the saving and what it costs, then let
  them decide.
- **Always list what it costs** besides tokens: harder to read, lost
  meaning (comments often say why the code is the way it is), harder for
  the next person or agent to change safely.
- **Label guesses.** A claim like "the model will still understand it" is
  a guess unless something measured it. Write "guess (not measured)" next
  to it. Do not test quality here: that costs money and needs its own
  research issue and budget.

## 4. Record it

Always write it down, also when the answer is "no" and when the user
still has to decide. That is what stops the next agent from measuring the
same trick again.

- **Where:** GitHub issues if `gh repo view` works. Otherwise an `issues/`
  folder: the index is `issues/0-research-index.md`, and each issue is
  `issues/<next number>-<topic>.md` with `labels: research` on line 1 and
  `state: open` or `state: closed` on line 2.
- **The issue:** use the `issues-first` Research template if you have it.
  If not, these four sections are enough: "Question", "Runs" (date, sample,
  tokenizer, form tried, before, after, change), "Verdict", "Retry when".
- **The verdict:** `drop` below the threshold, `adopt` if the user said yes,
  `waiting on user` until they answer. Close the issue once it is `drop`
  or `adopt`.
- **The index row**, numbers in the verdict. Create the index with this
  header if it doesn't exist:

```markdown
| # | Question | State | Verdict | Retry when |
|---|---|---|---|---|
| #14 | Do short variable names save tokens? | closed | drop: +0.4% to +2.6% tokens on 33 PRs (o200k_base) | you switch to a model with a different tokenizer |
```

## Rules

- Never apply a token-saving trick that has not been counted on this
  project's real files.
- Always name the tokenizer and the sample size with the number.
- An unmeasured claim about quality is a guess, and is labelled one.
