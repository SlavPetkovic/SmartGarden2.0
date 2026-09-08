---
description: Open a pull request for the current branch, wait for CI, and merge it on green
argument-hint: [optional one-line title]
---

Ship the current branch.

You have full authority to complete this without asking. The required status
checks are the reviewer — `docs/git-workflow.md` §1 explains what replaced the
human one. Merge on green, stop on red.

**1. Check where you are.**

```bash
git branch --show-current
git status --short
```

Refuse to continue if the branch is `main`, or if the working tree is dirty
with anything you did not intend to commit.

**2. Run the gate locally first.** A pull request that fails CI on checks you
could have run in eight seconds wastes a round trip.

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/python scripts/gate.py
```

Fix anything red before pushing.

**3. Push and open the pull request.**

```bash
git push -u origin "$(git branch --show-current)"
gh pr create --base main --title "$1" --body-file <(...)
```

Write the body to the shape in `docs/git-workflow.md` §6. Fill in every
section, and fill in **"What I was unsure about"** honestly — what you guessed,
what you assumed about the physical world, what a person should look at. That
section is the point of the template. Leaving it empty on a substantial change
is a signal that you have not looked.

If the change touches tuning, a safety constant, a contract document, or
removes tests, add the matching token line (`TUNING-CHANGE:`,
`SAFETY-CHANGE:`, `CONTRACT-CHANGE:`, `TEST-REMOVAL:`) with a real reason.
`docs/git-workflow.md` §4 has examples. If the honest reason for a
`TUNING-CHANGE` is that you needed a number and did not have one, do not write
the token — stop, because that is the soak gate.

**4. Wait for CI. Actually wait.**

```bash
gh pr checks --watch
```

**5. Then, and only then:**

```bash
gh pr merge --squash --delete-branch
```

Never `--admin`. Never on a pending check. Never by disabling a check or
re-running one until it flakes green — if a check is flaky, say so in a comment
and fix the flake in its own pull request.

**6. If this completed a layer**, tag it and say so:

```bash
git switch main && git pull --ff-only
git tag -a layer-NN -m "Layer NN — <name> · <requirement IDs>"
git push origin layer-NN
```

**If CI is red**, do not merge and do not work around it. Fix the cause, push
again, wait again. If three pushes do not clear it, or if clearing it would
mean changing a requirement, a safety constant, a threshold or a test's intent,
write `.autobuild/BLOCKED-<layer>.md` saying what is in the way and stop. A
blocked layer is a good outcome; a layer that merged because a check was
silenced is not.

Report at the end: the pull request URL, whether it merged, and anything from
"what I was unsure about" that a person should act on.
