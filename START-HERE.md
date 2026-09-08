# START HERE

Two audiences. §1 is for Slav, once. §2 is the text to paste into Claude Code
on the Pi.

---

## 1. Standing this up (once, by hand)

**On the laptop**, from this folder, with `gh` authenticated:

```bash
bash setup/bootstrap-repo.sh smartgarden --dry-run   # read what it will do
bash setup/bootstrap-repo.sh smartgarden
```

That creates the repository, pushes this tree as the initial commit, sets
squash-only merges, and protects `main` with the CI checks as the gate and no
required approvals. It prints a "What you got" block at the end saying whether
branch protection actually took — on a free plan with a private repository it
cannot, and the block explains what that means and how to fix it.

**On the Pi:**

```bash
git clone https://github.com/SlavPetkovic/smartgarden.git ~/SmartGarden
cd ~/SmartGarden

mkdir -p .claude/commands
cp setup/claude/settings.json  .claude/settings.json
cp setup/claude/commands/*.md  .claude/commands/

python3 -m venv .venv
.venv/bin/pip install -e ".[pi,web,dev]"

gh auth login        # Claude Code pushes and merges as you, through this
claude doctor        # confirm the permission rules resolved
claude
```

`gh auth login` is the step that hands over the authority. Everything Claude
Code does to the repository — push, pull request, merge, tag — goes through
that token, as you.

---

## 2. Paste this into the first Claude Code session

> There is an existing SmartGarden prototype running on this Pi at port 8000,
> built from a different brief. It is not the system we are building and it is
> not to be patched, imported from, or used as a reference for structure. This
> repository is the build.
>
> Read `docs/architecture.html` — the 72 numbered requirements are the
> contract. Then `CLAUDE.md` for the hard rules, `docs/BUILD-PLAN.md` for the
> layer gates and the autonomy contract, and `docs/git-workflow.md` for what
> you may and may not do to this repository. Where they disagree, the
> architecture document wins.
>
> **You own this repository.** You branch, commit, push, open pull requests,
> wait for CI, merge to `main`, and tag layers, without asking. There is no
> human approving your pull requests. What replaced that reviewer is the
> required status checks: the test suite run with zero dependencies, ruff,
> mypy, `scripts/gate.py` for the structural invariants, and
> `scripts/diff_gate.py` for changes that have to be declared. Merge on green.
> Never on red, never with `--admin`, never by editing a check to make today's
> work pass. A change to a check goes in its own pull request.
>
> Before building anything, do the harvest in §4 of `docs/realign.md`: get the
> install workaround, the confirmed I2C addresses, the VEML7700 gain and
> integration time, the observed value ranges, and a copy of the prototype's
> SQLite file. Report what you found. If the BME680 answered at an address that
> disagrees with `config/sensors.toml`, that is the one edit to that file you
> are allowed, and say so in the commit message.
>
> Then `/next-layer 02`.
>
> Three things to hold on to as you go, because the prototype got each of them
> wrong and everything else rests on them:
>
> 1. A rule or UI element names a **role** in a zone, never a driver, a field
>    name or an I2C address (DATA-3, SCOPE-3).
> 2. Measurements are **rows, not columns** — adding a sensor must never
>    require a migration (DATA-1).
> 3. Nothing in stage A builds an actuation path at all. If a gate looks like
>    it needs a moisture threshold, that is the soak gate and the answer is to
>    stop, not to guess. `automation_enabled` stays false until a person has
>    read a week of real readings and created `.stage-b-complete` by hand.
>
> Every pull request has a "What I was unsure about" section. Fill it in
> honestly. In a repository where pull requests merge themselves, that section
> is the only place doubt has to go.

For every layer after 02, `/next-layer NN` carries its own gate and needs no
further briefing. `/ship` takes a finished branch to `main`.

---

## 3. What is different from before

The autonomy posture changed on 2026-09-08, from *full auto on a work branch,
a person merges* to *full auto through to `main`, CI merges*. Three things
carry the weight that the human merge step used to:

| | |
|---|---|
| `.github/workflows/ci.yml` | tests with no dependencies installed, ruff, mypy, pytest + coverage |
| `scripts/gate.py` | `core/` purity, no `RPi.GPIO`, no third-party base deps, no silenced tests, automation off in stage A |
| `scripts/diff_gate.py` | tuning, safety constants, contract documents and shrinking test suites must be declared in the pull request body |

The third is the interesting one. It forbids nothing. It makes three kinds of
change impossible to make quietly — and the first of those, editing
`config/plants.toml`, is exactly what went wrong last time, when
`moisture < 30%` and a 180 s daily cap were invented rather than measured.

Claude Code can now edit those files. It cannot do it silently.

**Still denied outright:** `sudo`, `systemctl start|stop|restart`, force-pushing
or deleting `main`, `gh pr merge --admin`, and creating `.stage-b-complete`.
The running control service is not the build's to restart, and the soak
sign-off is not the build's to sign.
