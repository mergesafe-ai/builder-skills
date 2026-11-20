# Agent instructions

## Every skill is measured before it merges

This applies to every new skill and every change to a skill's `SKILL.md`.

1. **Trigger test.** Make a small scratch project outside this repo (git init,
   a few realistic source files, a README). Run
   `python3 scripts/trigger_test.py <fixture> <prompts.tsv>`: it copies the
   skills in, runs Claude Code headless 3 times per prompt, and prints which
   skill loaded. The prompts must include:
   - positive prompts the user asks ("try caching to see if it's faster");
   - positive prompts where the agent itself decides to act ("the build is slow, make it faster");
   - negatives, where no skill should load ("fix this typo in README").

   `scripts/trigger_prompts.tsv` is an example, written for a small Flask
   notes app with a `prompts/` folder, a `build.sh` and a `README.md`.
2. **Behavior test.** Fresh agents follow the skill end to end on the
   fixture, including a negative case where the skill should stop or say no.
3. **Results in the PR.** Put the trigger table and the behavior results in
   the pull request body.

A skill that doesn't load when it should, or loads when it shouldn't, does
not merge.

Never file test issues, pull requests or fixtures in this repo. It is
public. Tests run in a scratch directory.
