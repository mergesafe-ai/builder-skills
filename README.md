# Security skills for builders

Free security checks you can run on your own repo with Claude Code or any
agent that reads `SKILL.md` files.

## Skills

- **cve-reachability**: finds known security holes in the libraries your app
  uses, then checks whether your code actually calls the broken part.

## Run it

```bash
python3 skills/cve-reachability/scripts/osv_lookup.py /path/to/your/repo
```

Needs Python 3.11+ and internet access (queries https://api.osv.dev). No API key, no dependencies.

## Limits

- Python (`uv.lock`) and npm (`package-lock.json`) only for now.
- A missing match in the code is not proof a library is safe.
