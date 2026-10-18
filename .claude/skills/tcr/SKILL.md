---
name: tcr
description: Start, check or finish a TCR (test && commit || revert) session. Green steps are auto-committed and red steps auto-reverted by a Stop hook on tcr/* branches.
disable-model-invocation: true
argument-hint: "start <topic> | status | finish"
allowed-tools: Bash(git *)
---

# TCR mode

Requested action: $ARGUMENTS

The Stop hook `.claude/hooks/tcr.py` does the enforcement. It is active only while the current branch starts with `tcr/`. At the end of every turn it runs `tcr.test_cmd` from `.claude/method-kit.json`: if the tests pass it commits everything, and if they fail it moves all uncommitted changes into a stash named `tcr-revert ...` and sends you back to try a smaller step.

## start <topic>

1. Run `git status --porcelain`. If anything is uncommitted, stop and ask the user to commit or stash it first. Do not do it for them.
2. Read `tcr.test_cmd` from `.claude/method-kit.json`. If it is empty, stop and ask the user for the fast test command.
3. Run the test command once on the current HEAD. If it fails, stop: TCR needs a green baseline. Show the failure.
4. Create the branch from the current one: `git switch -c tcr/<topic-in-kebab-case>`, then remember the base with `git config branch.tcr/<topic>.tcrBase <previous-branch>`.
5. Tell the user in two lines that TCR is on, and that leaving the branch turns it off.

## status

Show the current branch, `git log --oneline -10` for the branch, and the number of `tcr-revert` stashes (`git stash list | grep -c tcr-revert`). Remind the user of the working rules below in one short paragraph.

## finish

1. The tree must be clean and the last turn green. If not, say so and stop.
2. Find the base: `git config branch.<current>.tcrBase`, falling back to `main`.
3. Show `git log --oneline <base>..HEAD` and propose a single squash commit message that summarizes the behavior change.
4. Ask the user to confirm before merging. On yes: `git switch <base> && git merge --squash <tcr-branch> && git commit -m "<message>"`.
5. Then ask whether to delete the TCR branch and drop its `tcr-revert` stashes. Do only what the user approves.

## Working rules on a tcr/* branch

These apply for the whole session while the branch starts with `tcr/`, not only right after this skill runs.

- Each turn is one small step that leaves every test green. A few lines is the right size. A reverted step means the step was too big, so split it.
- Keep structure and behavior apart: a pure tidy-up (rename, extract, move) is its own turn, and a behavior change comes in a later turn together with the test that covers it.
- Never end a turn red. If you need to ask the user something mid-change, first get back to green: finish the step or undo your own partial edits.
- After a revert: do not `git stash pop` or `git stash apply` the reverted work. Re-derive a smaller step instead.
- Never weaken, skip or delete tests, and never change the test command to get green.
- Do not run `git commit` yourself. The hook commits.
