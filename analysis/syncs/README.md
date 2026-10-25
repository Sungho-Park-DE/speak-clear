# analysis/syncs

The only place where modules meet (the sync/gate layer). A gate function picks a module version by feature flag. Flags default to off, so turning one off keeps the current behavior. Check a flag with `is_enabled("pitch_v2")` in `flags.py`; it reads the comma-separated environment variable `VP_FLAGS` (create it together with the first gate). Modules never import each other; they are combined only here.
