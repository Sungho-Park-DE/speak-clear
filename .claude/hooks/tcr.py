#!/usr/bin/env python3
"""TCR (test && commit || revert) for Claude Code -- a Stop hook.

Active only while the current git branch starts with tcr.branch_prefix
(default "tcr/"). At the end of every Claude turn:

  * no uncommitted changes  -> nothing happens
  * tests pass              -> `git add -A && git commit` (one green step)
  * tests fail or time out  -> every uncommitted change is moved into a stash named
                               "tcr-revert ..." and Claude is told to retry in a
                               smaller step. After N reverts in a row Claude is
                               allowed to stop and you get a notice instead.

Safety: this script never runs `git reset --hard` or `git clean`. Reverted work
is always recoverable with `git stash list` / `git stash apply stash@{n}`.

Config: .claude/method-kit.json -> "tcr". Standard library only, Python 3.8+.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

CONFIG_REL = Path(".claude") / "method-kit.json"
COUNTER_NAME = "tcr-fail-count"
DEFAULTS = {
    "test_cmd": "",
    "branch_prefix": "tcr/",
    "timeout_sec": 300,
    "max_consecutive_reverts": 3,
    "commit_no_verify": True,
    "output_tail_chars": 3000,
}


def git(repo, *args, timeout=60):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=timeout)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def load_config(repo: Path) -> dict:
    candidates = [repo / CONFIG_REL]
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidates.append(Path(project_dir) / CONFIG_REL)
    cfg = dict(DEFAULTS)
    for path in candidates:
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                cfg.update((json.load(fh).get("tcr") or {}))
            break
    return cfg


def run_tests(cmd: str, repo: Path, timeout: int):
    """Run the test command in its own process group so a timeout kills everything."""
    env = os.environ.copy()
    # Fresh bytecode only: a stale __pycache__ entry (same mtime second, same size)
    # could otherwise turn a red step green.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    proc = subprocess.Popen(
        cmd, shell=True, cwd=str(repo), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True, env=env,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode == 0, out or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        out, _ = proc.communicate()
        return False, (out or "") + f"\n[TCR] test command timed out after {timeout}s"


def tail(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else "...\n" + text[-limit:]


def commit_message(payload: dict) -> str:
    last = payload.get("last_assistant_message") or ""
    if isinstance(last, list):  # defensive: content blocks
        last = " ".join(b.get("text", "") for b in last if isinstance(b, dict))
    for line in str(last).splitlines():
        line = re.sub(r"[`*#>_]+", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        if line:
            return "tcr: " + (line[:69] + "..." if len(line) > 72 else line)
    return "tcr: green step"


def read_counter(path: Path) -> int:
    try:
        return int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0


def write_counter(path: Path, value: int) -> None:
    try:
        path.write_text(str(value))
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    top = git(cwd, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return 0  # not a git repository: TCR does not apply
    repo = Path(top.stdout.strip())
    cfg = load_config(repo)

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not branch.startswith(cfg["branch_prefix"]):
        return 0  # TCR is only active on tcr/* branches
    test_cmd = (cfg.get("test_cmd") or "").strip()
    if not test_cmd:
        emit({"systemMessage": "TCR is inactive: you are on a tcr branch but tcr.test_cmd "
                               "is empty in .claude/method-kit.json."})
        return 0
    if not git(repo, "status", "--porcelain").stdout.strip():
        return 0  # nothing changed this turn

    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").stdout.strip())
    counter = git_dir / COUNTER_NAME
    max_reverts = int(cfg["max_consecutive_reverts"])
    limit = int(cfg["output_tail_chars"])

    passed, output = run_tests(test_cmd, repo, int(cfg["timeout_sec"]))

    if passed:
        message = commit_message(payload)
        add = git(repo, "add", "-A")
        commit_args = ["commit", "-q", "-m", message] + (["--no-verify"] if cfg["commit_no_verify"] else [])
        commit = git(repo, *commit_args) if add.returncode == 0 else add
        if commit.returncode != 0:
            emit({"systemMessage": "TCR: tests passed but the commit failed, so nothing was committed:\n"
                                   + tail(commit.stdout + commit.stderr, 1500)})
            return 0
        write_counter(counter, 0)
        sha = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        emit({"systemMessage": f"TCR green: committed {sha} ({message})"})
        return 0

    # Red: move everything uncommitted into a recoverable stash.
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    label = f"tcr-revert {stamp} on {branch}"
    stash = git(repo, "stash", "push", "--include-untracked", "-m", label)
    still_dirty = bool(git(repo, "status", "--porcelain").stdout.strip())
    if stash.returncode != 0 or still_dirty:
        emit({"decision": "block",
              "reason": "TCR: the tests failed AND the automatic revert (git stash) did not leave a clean "
                        "tree:\n" + tail(stash.stdout + stash.stderr, 1500) +
                        "\nStop coding. Tell the user that TCR could not revert, show `git status`, and wait."})
        return 0

    attempts = read_counter(counter) + 1
    if attempts >= max_reverts:
        write_counter(counter, 0)
        emit({"systemMessage": f"TCR red: reverted again ({attempts} in a row). The retry loop stopped here. "
                               f"Reverted attempts are saved in `git stash list` (tcr-revert ...)."})
        return 0
    write_counter(counter, attempts)
    emit({
        "decision": "block",
        "reason": (
            f"TCR red: the test command failed, so ALL uncommitted changes were reverted to the last green "
            f"commit (saved as stash '{label}', attempt {attempts}/{max_reverts}).\n\n"
            f"Test command: {test_cmd}\nOutput (tail):\n{tail(output, limit)}\n\n"
            "Next: redo the work as a SMALLER step that keeps every test green, then end your turn so TCR "
            "can commit it. Do not `git stash pop/apply` the reverted work, do not weaken, skip or delete "
            "tests, do not change the test command, and do not commit yourself."
        ),
    })
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the session because of the hook itself
        print(f"tcr hook error: {exc}", file=sys.stderr)
        sys.exit(1)
