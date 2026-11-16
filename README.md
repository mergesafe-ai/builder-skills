# Security checks for builders

You shipped with libraries you didn't write. Some of them probably have a
known security hole that someone already published, with a fix that's
already out. This repo has free checks that find those, and tell you whether
your code actually hits the broken part.

## What you get

**End a long session cleanly** (`handoff`)

- Saves what got done, what's open and the next step in one short file.
- A fresh session picks it up without re-reading the whole old chat, which is where most agent token spend goes.
- Measure it on your own sessions first: `python3 skills/handoff/scripts/measure.py` reads your local Claude Code logs and estimates what handoffs would save you. Nothing leaves your machine.


**Check your dependencies** (`cve-reachability`)

- Lists every library your app pins, and flags the ones with a known security hole.
- For each one: what the hole lets someone do, the version that fixes it, and how long it has been public.
- Looks through your code and says whether you use the broken part. If it can't tell, it says that too.

## Run it on your app

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

## License

MIT. Use it, fork it, and send fixes.
