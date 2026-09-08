# Git authority

Claude Code owns this repository end to end: branching, committing, pushing,
opening pull requests, waiting on CI, merging, tagging, releasing. No human
approval is required for a merge to `main`.

That is a real transfer of authority, so it is worth being precise about what
holds it up. This document is the contract. `CLAUDE.md` has the hard rules
about the code; this one is about the repository.

---

## 1. What replaced the human reviewer

Nothing merges on trust. Three things merge a pull request:

| | What it checks | Where |
|---|---|---|
| **CI** | tests with zero dependencies, ruff, mypy, pytest + coverage | `.github/workflows/ci.yml` |
| **Guard rails** | `core/` purity, no `RPi.GPIO`, no third-party base deps, no silenced tests, automation off in stage A | `scripts/gate.py` |
| **Tripwires** | tuning edits, safety-constant edits, a shrinking suite | `scripts/diff_gate.py` |

CI and the guard rails are pass/fail. The tripwires are different: they do not
forbid anything, they refuse to let it happen quietly. Each one clears when the
pull request body says what changed and why (§4).

All three are required status checks on `main`. Red means stop.

GitHub does not let an author approve their own pull request, so there is no
approval step to fake. The checks above are the review, which means weakening
one of them is not a shortcut — it is the failure mode this whole arrangement
is built to prevent.

---

## 2. The loop

```
git switch -c auto/layer-03            branch per layer, or fix/<slug>, docs/<slug>
                                       never commit directly to main
... build, commit as often as useful ...

python scripts/gate.py                 run the guard rails locally first
PYTHONPATH=src python -m unittest discover -s tests -t .

git push -u origin auto/layer-03
gh pr create --fill                    body follows the template
gh pr checks --watch                   wait. do not merge on a pending check
gh pr merge --squash --delete-branch   green only
```

`/ship` does all of that in one step, including refusing to merge on red.

**Squash merges, one commit per layer on `main`.** `main` reads as the build
plan: layer 01, layer 02, layer 03. A layer that had eleven attempts inside it
is still one commit, and reverting a layer is `git revert <sha>`.

**The branch is deleted on merge.** A stale `auto/layer-03` sitting around after
its merge is how the next session ends up building on top of yesterday.

---

## 3. What Claude Code may do, and what it may not

**May, without asking:**

- create, push, force-push and delete `auto/*`, `fix/*`, `docs/*`, `chore/*` branches
- open, edit, comment on and close its own pull requests
- merge to `main` by squash, when every required check is green
- create tags and GitHub releases at layer boundaries
- create, label, and close issues
- edit any file the permission envelope in `setup/claude/settings.json` allows

**May not, ever:**

- **force-push `main`**, rewrite its history, or delete it
- **merge on a red or pending check**, or with `--admin`, or by disabling a check
- **change `.github/workflows/*` or `scripts/gate.py` in the same pull request as the
  work whose gate they check** — a change to the gate goes in its own pull
  request, on its own, saying what it changes and why
- **run `sudo`**, or `systemctl start|stop|restart|enable|disable` — the running
  control service is not the build's to restart
- **set `automation_enabled = true`** before the soak is signed off (§5)
- close or merge a pull request a person opened

If one of those turns out to be genuinely necessary, that is a stop condition:
write `.autobuild/BLOCKED-NN.md` saying which and why, and wait.

---

## 4. Clearing a tripwire

Three kinds of change need a line in the pull request body. Not because they
are wrong — because a person skimming `main` six weeks from now needs to find
them.

```
TUNING-CHANGE: soak data 2026-09-14..21 puts the dry plateau at 640 counts,
               not the placeholder 800. Chart in the PR body.

SAFETY-CHANGE: max_on_seconds 5 -> 8. The 5 s pulse never wet the full root
               ball; measured over four cycles, not guessed.

TEST-REMOVAL:  test_altitude_channel deleted. altitude was never a declared
               channel (DATA-5) — the test asserted a bug.
```

A bare token with no reason after it does not clear the tripwire.

**A tripwire is not a formality to type past.** `TUNING-CHANGE` in particular
exists because the previous attempt shipped `moisture < 30%` with a 5 s pulse
and a 180 s cap, and every one of those numbers was invented. If the honest
reason is "I needed a number and did not have one", the answer is not a token.
It is to stop — that is the soak gate, and `docs/realign.md` §2 is what happens
when it gets skipped.

---

## 5. The soak gate, in repository terms

Stage A (layers 01–06) builds no actuation path at all. `scripts/gate.py`
enforces the visible half: `automation_enabled` may not be `true` while
`.stage-b-complete` is absent from the repository root.

That file is **created by a person**, by hand, after reading seven or more days
of real logged readings and editing `config/plants.toml` to the plateaus they
actually show. It is not Claude Code's to create, and a pull request that adds
it will be closed.

Order: `01 → 02 → 03 → 04a → 05 → 06`, then the soak, then `04b`.

---

## 6. Pull request shape

Title: `Layer 03 — Drivers` or `fix: VEML7700 integration time not recorded`.

Body:

```markdown
## What this is
Two or three sentences. What now works that did not before.

## Requirements satisfied
SENS-1, SENS-2, SENS-5, SAFE-2 — one line each on how.

## Gate
The acceptance gate for this layer is BUILD-PLAN.md §5, layer 03.
- [ ] every item in that gate is true
- [ ] `python scripts/gate.py` clean locally
- [ ] no actuation path added (stage A)

## What I was unsure about
The honest section. What was guessed, what was assumed about the physical
world, what a person should look at. Empty is a suspicious answer.
```

The last section matters more than the rest. A pull request that merges itself
needs somewhere to put doubt, and "what I was unsure about" is that place.

---

## 7. Tags and releases

At each layer boundary, after the merge:

```bash
git tag -a layer-03 -m "Layer 03 — Drivers · SENS-1…8, SAFE-2"
git push origin layer-03
```

The Pi deploys from a tag, never from `main`'s tip. That way a bad merge cannot
reach the hardware before a person has pulled it.

---

## 8. If CI is wrong

It happens. A guard rail can be wrong about a requirement.

Fix the check, in its own pull request, with the reasoning in the commit
message and the requirement ID it was wrong about. Never delete a check to make
today's work merge, and never move work into a shape that dodges a check rather
than satisfies it. `docs/BUILD-PLAN.md` §3 is the longer version of this
paragraph and it binds.
