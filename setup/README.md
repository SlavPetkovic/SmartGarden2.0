# setup/

Two things live here: the one-time repository bootstrap, and the files that
belong in `.claude/` and `.github/` but are staged here because the OneDrive
folder that synced this repository cannot write into a dotted config directory.

```
setup/bootstrap-repo.sh      run once, creates and configures the repository
setup/github/                copied to .github/ by the bootstrap script
setup/claude/                copied to .claude/ by hand, on the Pi
```

After the bootstrap has run once, `.github/` is under git like anything else
and is edited there directly — `setup/github/` is only the staging area that
gets it past the sync folder the first time.

## Once, to create the repository

From the repository root, on a machine where `gh` is authenticated as the
account that should own it:

```bash
bash setup/bootstrap-repo.sh smartgarden --dry-run   # read what it will do
bash setup/bootstrap-repo.sh smartgarden
```

It creates the repository, pushes this tree, sets squash-only merges, and
protects `main` with the CI checks as the gate and zero required approvals. It
finishes with a "What you got" block that says whether branch protection
actually took — on a free plan with a private repository the API refuses, and
the block explains what that means and how to fix it. Read that block; it is
the difference between a rule GitHub enforces and a rule Claude Code keeps.

## Once, on the Pi, before the first autonomous run

```bash
cd ~/SmartGarden
mkdir -p .claude/commands
cp setup/claude/settings.json  .claude/settings.json
cp setup/claude/commands/*.md  .claude/commands/
gh auth login          # this is what hands over repository authority
claude doctor          # confirm the permission rules resolved
```

- `settings.json` — the permission envelope for unattended runs. Its intent is
  documented in `docs/git-workflow.md` (what may be done to the repository) and
  `docs/BUILD-PLAN.md` §3 (what may be done in a build). The rules enforce most
  of it mechanically. Read it before trusting it.
- `commands/next-layer.md` — `/next-layer NN`, build one layer against its gate
  and take it to `main`.
- `commands/ship.md` — `/ship`, push the current branch, open the pull request,
  wait for CI, merge on green.

`gh auth login` is the step that matters. Everything Claude Code does to the
repository — push, pull request, merge, tag — goes through that token, as you.
There is no separate bot identity, which is also why there is no approval step:
GitHub does not let an author approve their own pull request, so the required
status checks are the review.

Keep all of it under git. If you change the contract in `docs/git-workflow.md`
or `docs/BUILD-PLAN.md` §3, change the rules here in the same commit — and in
its own pull request, since it is a gate change.
