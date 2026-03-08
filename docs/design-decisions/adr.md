# Architectural Decision Records (ADR)

This file follows the [MADR (Markdown Any Decision Records)](https://adr.github.io) format.
See [adr-template.md](adr-template.md) for the template. Append new records at the bottom of this file.

---

## [2026-03-02] Tech Stack Selection: Godot + GDScript + Rust

**Status:** Accepted

### Context and Problem Statement

Reversi Adventure is a 2D board game with heavy UI (story dialogs, menus, AI explanation text) targeting Steam release. All code is written by LLMs (AI-Centered Development). We need to select a game engine, programming language, and supporting libraries.

### Decision Drivers

- AI code generation friendliness (LLM training data volume, API stability)
- Code-only workflow (no visual editor dependency for LLM-generated code)
- Steam deployment maturity
- UI capability for a dialog/story-heavy board game
- Free asset ecosystem (no budget for paid assets)
- AI opponent performance (alpha-beta pruning for Reversi)

### Considered Options

1. **Godot + GDScript + Rust** (via godot-rust GDExtension)
2. **Go + Ebitengine**
3. **Pygame + Python + Rust** (via PyO3)
4. **Unity + C#**
5. **Bevy + Rust**
6. **Godot + gdext** (Rust only, no GDScript)
7. **Fyrox + Rust**
8. **Love2D + Lua**
9. **Defold + Lua**

### Decision Outcome

Chosen option: **Godot + GDScript + Rust**, because it provides the best balance of UI capability, Steam maturity, and LLM code generation friendliness for a dialog-heavy board game.

- **Game engine**: Godot 4.x with GDScript for UI, game flow, story, and menus
- **AI engine**: Rust via godot-rust GDExtension for the Reversi AI (alpha-beta pruning, evaluation, move explanation)
- **Steam integration**: GodotSteam (mature GDExtension plugin)

### Pros and Cons of Top Options

#### Godot + GDScript + Rust (Chosen)

- Good, because Godot has the best built-in UI system for dialog-heavy games (RichTextLabel, Control nodes, Dialogic plugin)
- Good, because GDScript is syntactically close to Python -- LLMs handle it reasonably well
- Good, because GodotSteam is battle-tested (394+ Godot games on Steam by mid-2025)
- Good, because Rust gives optimal performance for the AI engine
- Good, because all Godot project files are text-based and git-friendly (.tscn, .tres, .gd)
- Good, because 100% free: no licensing fees (Godot MIT, Rust MIT/Apache)
- Bad, because GDScript is underrepresented in LLM training data -- LLMs may hallucinate Godot 3.x patterns
- Bad, because godot-rust (gdext) has limited LLM training data (~26 repos) -- AI-generated Rust bindings may need manual correction
- Bad, because two-language architecture (GDScript + Rust) adds build complexity

#### Go + Ebitengine (Runner-up)

- Good, because Go is arguably the best mainstream language for LLM code generation (simple, strongly typed, enforced formatting)
- Good, because 100% code-only workflow with no editor dependency
- Good, because excellent API stability (v2.9.x, 12 years mature, semantic versioning)
- Good, because single binary deployment via `go build` with embedded assets
- Bad, because no built-in dialog/story system -- must build custom UI layer on top of ebitenui
- Bad, because smaller LLM training corpus for Ebitengine specifically (~600 repos)
- Rejected because the heavy UI requirement (story dialogs, AI explanation text, menus) would require building too much custom infrastructure

#### Pygame + Python + Rust (3rd)

- Good, because Python has the best LLM code generation accuracy of any language
- Good, because 100% code-only workflow
- Bad, because no UI framework -- entire dialog/menu system must be built from scratch
- Bad, because Steam deployment is fragile (PyInstaller + SteamworksPy is not a proven pipeline)
- Rejected because UI and Steam deployment gaps outweigh the LLM accuracy advantage

#### Unity + C# (4th)

- Good, because largest game dev ecosystem with best LLM training data
- Good, because most proven Steam deployment path (thousands of games)
- Bad, because deeply editor-centric -- LLMs cannot interact with Unity's visual editor
- Rejected because the code-only workflow requirement is fundamentally incompatible with Unity's design

#### Bevy + Rust (Last)

- Good, because best raw performance (pure Rust, zero-cost abstractions)
- Bad, because API breaks every 3-5 months (not yet 1.0)
- Bad, because immature UI system unsuitable for dialog-heavy games
- Bad, because LLMs struggle with rapidly evolving Bevy APIs (training data becomes stale within months)
- Rejected because API instability and UI immaturity make it the worst fit for this project

### Consequences

**Mitigations for identified risks:**
- Pin Godot version (4.x stable) and provide version context in LLM prompts
- Keep Rust scope minimal (AI engine only) to limit gdext surface area
- Use .tscn scene files where practical (they are text-based and AI-generatable)

---

## [2026-03-08] Locale, Language, and Timezone Strategy

**Status:** Accepted

### Context and Problem Statement

Reversi Adventure is a story-driven board game targeting Steam, which has a global audience. We need to decide the supported languages, locale handling, and timezone behavior for the game.

### Decision Drivers

- Primary target audience includes both English and Japanese speakers
- Steam's global distribution means players from many locales
- Story-heavy game with significant translatable text (dialogs, menus, AI explanations)
- Community contributions for additional languages should be possible post-launch

### Decision Outcome

- **Supported languages (initial):** English and Japanese
- **Default language:** English (fallback when user's locale is not supported)
- **Language selection:** Auto-detect from user's OS/Steam locale; allow manual override in settings
- **Timezone:** Determined by user's system locale (no hardcoded timezone)
- **Additional languages:** Deferred until after game completion; community contributions welcome (e.g., translation files contributed by volunteers)

### Consequences

**Positive:**
- Two-language support covers the primary audience without excessive i18n overhead
- Auto-detection provides good UX out of the box
- Using user's system timezone avoids confusion for save timestamps, play time tracking, etc.
- Designing for i18n from the start (even with only 2 languages) makes future language additions straightforward

**Negative:**
- All in-game text must be externalized into translation files from the beginning (no hardcoded strings)
- Two languages doubles the text content workload for story dialogs
- LLM-generated translations may need human review for quality, especially for story/narrative text

**Mitigations:**
- Use Godot's built-in localization system (TranslationServer, .po/.csv files)
- Keep AI explanation text templated where possible to reduce translation burden
- Provide a clear contribution guide for community translators

---
