# analysis/modules

Let It Slop module folder. Each folder directly under here is one independently replaceable module (named `<name>_v<N>`, e.g. `pitch_v2`). Modules never import each other, not even through their public entry (`__init__.py`); they meet only in `analysis/syncs`. When requirements change materially, do not edit the old module; write a new version with the `slop-module` skill. Detailed rules are in `.claude/rules/let-it-slop.md`, and `.claude/hooks/boundary_check.py` checks the import boundary after every edit.
