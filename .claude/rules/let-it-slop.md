---
paths:
  - "analysis/modules/**"
---

# Let It Slop: module rules

Every folder directly under `analysis/modules` is one isolated, replaceable module. Versions are separate modules (`<name>_v<N>`). The goal is blast-radius control: if a module breaks in production, it can be switched off with a feature flag without touching anything else.

- A module never imports another module, not even its public entry. Modules meet only in the app/sync layer at `analysis/syncs`. If you need similar logic, copy it into this module; duplication between modules is accepted.
- Code outside the modules imports a module only through its public entry (`__init__.py` / `index.ts`). The public entry is the module's interface: keep it small, explicit and stable. Care goes here, not into internals.
- Do not refactor or tidy the internals of a module that works. When requirements change materially, write a new version with the `slop-module` skill. Small bug fixes in place are fine.
- Modules do not own global state: the app owns the database schema and migrations. A module takes inputs, returns outputs and raises errors to the app layer.
- Keep a module's tests inside the module folder so they are deleted together with it.
- The PostToolUse boundary hook reports violations right after an edit. Fix them immediately. Never add exemptions or change `.claude/method-kit.json` to get around it.
