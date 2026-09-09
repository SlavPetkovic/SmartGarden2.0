---
description: Review the staged changes (or a branch / PR) against the hard rules and tripwires
argument-hint: [base ref, branch or PR number — defaults to staged changes]
---

Use the **code-reviewer** subagent to review **$1**.

- If `$1` is empty, review the staged changes (`git diff --cached`).
- If `$1` is a ref or a branch, review it against `main`.
- If `$1` is a number, review that pull request (`gh pr diff $1`).

The subagent is read-only. When it reports back, relay its findings grouped by
severity. If any **blocking** finding stands, or a required change-shape
declaration is missing from the pull request body, do not proceed to `/ship`
until it is resolved.
