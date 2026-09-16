# Investigate migration to Godot 4.7.2 stable

## Description

Record the current Godot baseline and create a focused follow-up for a future
engine migration. This issue deliberately records only version and source
facts; compatibility, API changes, export behavior, and new features must be
researched when the migration plan is written.

## Current state (2026-09-17)

- `godot/project.godot` declares project feature `4.6`.
- `godot/reversi.gdextension` declares `compatibility_minimum = 4.2`.
- `rust/reversi-godot/Cargo.toml` uses `godot = "0.4.5"`.
- `AGENTS.md` still says Godot 4.5, so the documented baseline has drifted
  from the project setting.
- The Godot archive lists **Godot 4.7.2 stable** (2026-08-18) as the latest
  stable release. Godot 4.8 was a development release at the time of review
  and is not a migration target.

## Future scope

- Write a dedicated execution plan before editing the project or Rust binding.
- Re-check the current stable Godot release and the compatible `godot-rust`
  version at planning time.
- Assess the official 4.7 migration guidance and Godot/GDExtension ABI and API
  compatibility.
- Define editor-open and platform export smoke tests before changing the
  baseline.
- Synchronize `AGENTS.md`, the project setting, and extension compatibility
  documentation only after the supported version is decided.

## References

- Godot archive: https://godotengine.org/download/archive/
- Godot release policy: https://docs.godotengine.org/en/4.5/about/release_policy.html
- Godot 4.7 migration guide: https://docs.godotengine.org/en/stable/tutorials/migrating/upgrading_to_godot_4.7.html

## Priority

Medium. Keep separate from AI-strength work so a GDExtension compatibility
regression cannot obscure search or evaluation results.
