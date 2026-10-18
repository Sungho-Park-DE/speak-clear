---
name: slop-module
description: Create a new module, or replace an existing one with a new version behind a feature flag, following Let It Slop (isolated, disposable modules). Use whenever a new feature module is needed, whenever requirements for an existing module change materially (write v2 instead of refactoring v1), and when ramping or deleting module versions. Triggers include "new module", "v2", "rewrite", "replace", "feature flag rollout", "Let It Slop", "모듈 새로 만들어", "갈아끼워", "v2로", "새 버전".
---

# Let It Slop: new module or new version

## Project specifics (filled in during setup)

- Modules root: `analysis/modules`
- Version folder naming: `<name>_v<N>`
- Gate and sync layer, the only place modules meet: `analysis/syncs`
- Feature-flag check: `is_enabled("pitch_v2")` in `analysis/syncs/flags.py`, which reads the comma-separated env var `VP_FLAGS` (create it together with the first gate)
- Fast test command: `npx playwright test --max-failures=1 --reporter=dot && uv run --with pytest --with praat-parselmouth --with numpy --with av pytest -q -x analysis`
- Concept specs, if concept design is used: `docs/concepts/`

## Decide first

- **Small bug fix** that keeps the module's contract: fix it in place. No new version.
- **Material change** to behavior, data flow or most of the internals: write a new version. Do not refactor the old one.
- **Brand-new capability**: new module, starting at version 1. If concept design is in use, spec the concept first with the `concept-design` skill.

## New version procedure

1. Read the module's public entry and, if it exists, its concept spec. Unless the user asked to change it, the new version exposes the same interface with the same names and signatures.
2. Create the new folder next to the old one and write it from scratch. Never import from the old version. Copying small pieces by hand is fine.
3. Write the public entry first, then the internals behind it.
4. Put tests inside the new folder. Carry over the old version's contract tests (tests of the public interface) so both versions are held to the same behavior.
5. Wire the gate in `analysis/syncs`: one function picks the implementation with the flag `<module>_v<N>`, default off. Flag off must leave today's behavior unchanged.
6. State: both versions work on the same data. If the new version needs schema changes, use expand, migrate, contract: add only backward-compatible schema now, and remove the old version's state only after the old version is deleted.
7. Write a short rollout note in the PR or commit message: flag name, ramp (0% → internal → 5% → 20% → 100%), the signal to watch, and the kill switch (flag off).
8. Run `python3 .claude/hooks/boundary_check.py --all` and the tests, then ask the `blast-radius-reviewer` subagent for a verdict.

## Deleting the old version

Only after the new version has served 100% stably and the user confirms: delete the old folder, its branch in the gate, the flag, and then any state that only the old version used, in that order.

## Do not

- Polish or refactor internals. Internals may be plain or repetitive; that is accepted.
- Introduce helpers shared between modules. Shared helpers recreate the coupling this method removes.
- Ship a new version without a flag-off path, or turn the flag on yourself. Ramping is the user's decision.
