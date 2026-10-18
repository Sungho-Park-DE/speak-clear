#!/usr/bin/env python3
"""Let It Slop boundary checker -- Claude Code PostToolUse hook + CLI.

Rules (configured in .claude/method-kit.json -> "boundaries"):
  R1  A file inside <modules_root>/<A>/ must not import from another module <B>/,
      not even its public entry. Modules only meet in the app / sync layer.
  R2  Code outside the modules may import a module only through its public entry
      (<B>/ itself, <B>/__init__.py, <B>/index.ts, ...), never its internals.

Every folder directly under a modules root is one module. Versions are separate
modules (billing_v1/ and billing_v2/), so v2 can never lean on v1.

Usage:
  boundary_check.py --hook           read a Claude Code hook payload on stdin and check
                                     the edited file; exit 2 + stderr on violation so
                                     Claude sees the message and fixes it
  boundary_check.py --all            check every tracked/untracked (non-ignored) source
                                     file; exit 1 on violation (use in CI)
  boundary_check.py FILE [FILE ...]  check the given files; exit 1 on violation

Python and JS/TS (import, export-from, require, dynamic import) are understood.
Standard library only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path

PY_EXT = {".py"}
JS_EXT = {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
CONFIG_REL = Path(".claude") / "method-kit.json"

DEFAULTS = {
    "modules_root": "",  # string or list of strings, relative to the repo root
    "public_entries": ["__init__.py", "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs"],
    "source_roots": [".", "src"],  # where absolute Python imports are resolved from
    "path_aliases": {},  # JS/TS path aliases, e.g. {"@/": "src/"}
    "exempt_paths": [],  # path prefixes that are never checked, e.g. ["tests/e2e/"]
    "allow_cross_module_public_imports": False,
}

JS_IMPORT_PATTERNS = [
    # import x from '...'; import {a, b} from '...'; import type {T} from '...'; import '...'
    re.compile(r"""(?:^|[;\s])import\s+(?:type\s+)?(?:[\w$*{}\s,]+?\s+from\s+)?["']([^"'\n]+)["']""", re.M),
    # export * from '...'; export {a} from '...'; export * as ns from '...'
    re.compile(r"""(?:^|[;\s])export\s+(?:type\s+)?(?:\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s+from\s+["']([^"'\n]+)["']""", re.M),
    re.compile(r"""\brequire\s*\(\s*["']([^"'\n]+)["']\s*\)"""),
    re.compile(r"""\bimport\s*\(\s*["']([^"'\n]+)["']\s*\)"""),
]


def norm(p: str) -> str:
    p = posixpath.normpath(p.replace("\\", "/"))
    return "" if p in (".", "") else p


def strip_ext(name: str) -> str:
    if name.endswith(".d.ts"):
        return name[: -len(".d.ts")]
    root, ext = posixpath.splitext(name)
    return root if ext in PY_EXT or ext in JS_EXT else name


def find_repo_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return Path(out.stdout.strip())


def load_config(repo: Path) -> dict | None:
    candidates = [repo / CONFIG_REL]
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir:
        candidates.append(Path(project_dir) / CONFIG_REL)
    for path in candidates:
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            cfg = dict(DEFAULTS)
            cfg.update(data.get("boundaries") or {})
            return cfg
    return None


class Checker:
    def __init__(self, repo: Path, cfg: dict) -> None:
        self.repo = repo
        roots = cfg.get("modules_root") or []
        if isinstance(roots, str):
            roots = [roots]
        self.roots = sorted({norm(r) for r in roots if norm(r)}, key=len, reverse=True)
        self.entry_stems = {strip_ext(e) for e in cfg.get("public_entries") or []}
        self.source_roots = [norm(s) for s in cfg.get("source_roots") or ["."]]
        aliases = cfg.get("path_aliases") or {}
        self.aliases = sorted(((k, norm(v)) for k, v in aliases.items()), key=lambda kv: -len(kv[0]))
        self.exempt = [norm(e) for e in cfg.get("exempt_paths") or [] if norm(e)]
        self.allow_public_cross = bool(cfg.get("allow_cross_module_public_imports"))

    @property
    def active(self) -> bool:
        return bool(self.roots)

    # -- location helpers -------------------------------------------------
    def split_root(self, rel: str):
        """Return (root, parts below root) if rel is the root or below it, else None."""
        for root in self.roots:
            if rel == root:
                return root, []
            if rel.startswith(root + "/"):
                return root, rel[len(root) + 1:].split("/")
        return None

    def source_module(self, rel: str):
        hit = self.split_root(rel)
        if hit and len(hit[1]) >= 2:
            return hit[0], hit[1][0]
        return None  # outside the modules, or a loose file directly in a modules root

    def classify(self, rel: str):
        """Return ((root, module), is_public) if rel points into a module, else None."""
        hit = self.split_root(rel)
        if not hit or not hit[1]:
            return None
        root, parts = hit
        module = parts[0]
        if len(parts) == 1:
            # "<root>/<module>": the module package itself, unless it is a loose file.
            if (self.repo / root / module).is_dir():
                return (root, module), True
            return None
        rest = parts[1:]
        if len(rest) == 1 and strip_ext(rest[0]) in self.entry_stems:
            return (root, module), True
        return (root, module), False

    def is_exempt(self, rel: str) -> bool:
        return any(rel == e or rel.startswith(e + "/") for e in self.exempt)

    # -- import extraction -----------------------------------------------
    def py_exists(self, rel: str) -> bool:
        base = self.repo / rel
        return base.is_dir() or base.with_name(base.name + ".py").is_file()

    def py_abs_candidates(self, dotted: str):
        if not dotted:
            return
        seen = set()
        for source_root in self.source_roots:
            cand = norm(posixpath.join(source_root, *dotted.split(".")))
            if cand not in seen and self.split_root(cand) is not None:
                seen.add(cand)
                yield cand

    def py_imports(self, rel: str, text: str):
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return []
        pkg_dir = posixpath.dirname(rel)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for cand in self.py_abs_candidates(alias.name):
                        found.append((node.lineno, alias.name, cand))
            elif isinstance(node, ast.ImportFrom):
                label = "." * node.level + (node.module or "")
                if node.level:
                    base = pkg_dir
                    for _ in range(node.level - 1):
                        base = posixpath.dirname(base)
                    if node.module:
                        base = posixpath.join(base, *node.module.split("."))
                    bases = [norm(base)]
                else:
                    bases = list(self.py_abs_candidates(node.module or ""))
                for base in bases:
                    for alias in node.names:
                        if alias.name == "*":
                            found.append((node.lineno, label + ".*", base))
                            continue
                        sub = norm(posixpath.join(base, alias.name))
                        target = sub if self.py_exists(sub) else base
                        sep = "" if label.endswith(".") else "."
                        found.append((node.lineno, f"{label}{sep}{alias.name}", target))
        return found

    def js_target(self, rel: str, spec: str):
        if spec.startswith("."):
            return norm(posixpath.join(posixpath.dirname(rel), spec))
        for prefix, target in self.aliases:
            bare = prefix.rstrip("/")
            if spec == bare or spec.startswith(prefix):
                return norm(posixpath.join(target, spec[len(prefix):] if spec != bare else ""))
        return None  # a package import such as 'react'

    def js_imports(self, rel: str, text: str):
        # Blank out comments but keep line numbers stable.
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        text = re.sub(r"(?m)^\s*//.*$", "", text)
        found = []
        for pattern in JS_IMPORT_PATTERNS:
            for match in pattern.finditer(text):
                spec = match.group(1)
                target = self.js_target(rel, spec)
                if target is not None:
                    lineno = text.count("\n", 0, match.start(1)) + 1
                    found.append((lineno, spec, target))
        return found

    # -- rules ------------------------------------------------------------
    def check_file(self, rel: str):
        if not self.active or self.is_exempt(rel):
            return []
        ext = posixpath.splitext(rel)[1]
        if ext not in PY_EXT and ext not in JS_EXT:
            return []
        try:
            text = (self.repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        imports = self.py_imports(rel, text) if ext in PY_EXT else self.js_imports(rel, text)
        src = self.source_module(rel)
        problems, seen = [], set()
        for lineno, label, target in sorted(imports):
            hit = self.classify(target)
            if hit is None:
                continue
            (root, module), public = hit
            if src is not None:
                if (root, module) == src:
                    continue
                if public and self.allow_public_cross:
                    continue
                msg = (f"L{lineno}: `{label}` reaches into module '{module}' from module '{src[1]}'. "
                       f"Modules must not import each other. Duplicate what you need inside "
                       f"'{src[1]}', or move the wiring to the app/sync layer.")
            else:
                if public:
                    continue
                msg = (f"L{lineno}: `{label}` imports internals of module '{module}'. "
                       f"Go through its public entry ({root}/{module}/) instead, "
                       f"or expose what you need from that entry.")
            if msg not in seen:
                seen.add(msg)
                problems.append(msg)
        return problems


def report(results: dict) -> str:
    lines = []
    for rel, problems in results.items():
        lines.append(f"Let It Slop boundary violation(s) in {rel}:")
        lines.extend(f"  {p}" for p in problems)
    lines.append("Fix these before continuing (see .claude/rules/let-it-slop.md). "
                 "Do not silence the checker or add exemptions to get around it.")
    return "\n".join(lines)


def list_source_files(repo: Path):
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=str(repo), capture_output=True, text=True, timeout=60,
    )
    for line in out.stdout.splitlines():
        ext = posixpath.splitext(line)[1]
        if ext in PY_EXT or ext in JS_EXT:
            yield line


def run_hook() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    fpath = Path(file_path)
    if not fpath.is_absolute():
        fpath = cwd / fpath
    start = fpath.parent if fpath.parent.is_dir() else cwd
    repo = find_repo_root(start)
    if repo is None:
        return 0
    cfg = load_config(repo)
    if cfg is None:
        return 0
    checker = Checker(repo, cfg)
    if not checker.active:
        return 0
    try:
        rel = fpath.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return 0
    problems = checker.check_file(rel)
    if not problems:
        return 0
    print(report({rel: problems}), file=sys.stderr)
    return 2


def run_cli(paths, check_all: bool) -> int:
    repo = find_repo_root(Path.cwd())
    if repo is None:
        print("boundary_check: not inside a git repository", file=sys.stderr)
        return 3
    cfg = load_config(repo)
    if cfg is None:
        print(f"boundary_check: {CONFIG_REL} not found", file=sys.stderr)
        return 3
    checker = Checker(repo, cfg)
    if not checker.active:
        print("boundary_check: boundaries.modules_root is empty -- nothing to check", file=sys.stderr)
        return 3
    if check_all:
        rels = list(list_source_files(repo))
    else:
        rels = []
        for p in paths:
            try:
                rels.append(Path(p).resolve().relative_to(repo.resolve()).as_posix())
            except ValueError:
                print(f"boundary_check: skipping {p} (outside the repository)", file=sys.stderr)
    results = {}
    for rel in rels:
        problems = checker.check_file(rel)
        if problems:
            results[rel] = problems
    if results:
        print(report(results))
        return 1
    print(f"boundary_check: OK ({len(rels)} file(s) checked, roots: {', '.join(checker.roots)})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Let It Slop module boundary checker")
    parser.add_argument("--hook", action="store_true", help="run as a Claude Code PostToolUse hook")
    parser.add_argument("--all", action="store_true", help="check all source files in the repo")
    parser.add_argument("paths", nargs="*", help="files to check")
    args = parser.parse_args()
    if args.hook:
        return run_hook()
    if not args.all and not args.paths:
        parser.print_help()
        return 3
    return run_cli(args.paths, args.all)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except json.JSONDecodeError as exc:
        print(f"boundary_check: invalid JSON in {CONFIG_REL}: {exc}", file=sys.stderr)
        sys.exit(1)
