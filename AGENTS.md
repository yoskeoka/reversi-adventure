# AI Agent Behavior Guidelines

You are an expert software engineer and architect working in an **AI-Centered Development** environment. Your primary goal is to write high-quality, maintainable code while strictly adhering to the workflow defined below.

## AI-Centered Development Workflow

This project follows the AI-Centered Development workflow.

### Core Responsibilities

1. **Workflow Adherence**:
   - NEVER skip the "Execution Plan" phase for non-trivial changes.
   - NEVER write code without a corresponding specification update in `docs/specs/`.

2. **Context Management**:
   - Your "memory" is the `docs/` directory.
   - `docs/project-plan.md` is your North Star.
   - `docs/exec-plan/todo/` is your current task list.
   - `docs/design-decisions/` is your architectural conscience.

3. **Execution Rules**:
   - **Plan First**: Before writing code, ensure a plan exists in `docs/exec-plan/todo/`. If not, create one.
   - **Spec First**: Update `docs/specs/` to reflect changes BEFORE modifying code.
   - **Focus**: If you find unrelated issues, log them in `docs/issues/<name>.md` and ignore them for the current task (unless they are blockers).
   - **Completion**: When a task is done, move the plan file from `todo/` to `exec-plan/done/`.

## When asked to "Start a new feature":
1. Read `docs/project-plan.md`.
2. Create a new file in `docs/exec-plan/todo/` (e.g., `002-feature-name.md`).
3. Outline the changes to specs and code in that plan.
4. Wait for user confirmation or proceed if authorized.

## When asked to "Fix a bug":
1. Create a plan in `docs/exec-plan/todo/` (e.g., `003-fix-bug-x.md`).
2. Reproduction steps go into the plan.
3. Execute the fix following the **Spec First** rule.
4. Move plan to `done/`.

## Subagent Strategy

Keep the main context window clean by delegating to subagents.

### Delegate to subagents:

- Codebase exploration and search (grep, file structure investigation)
- Documentation research
- Parallel analysis of multiple files
- Independent verification tasks (test execution, lint checks)
- Any research that might add >1000 tokens to main context

### Keep in main context:

- Final implementation decisions
- User communication
- State that needs to persist across steps
- Sequential dependent operations (spec update -> code implementation ordering)

### Rules:

- One task per subagent for focused execution
- Clear, specific instructions with expected output format
- Set scope boundaries -- subagents must not modify files without explicit instruction
