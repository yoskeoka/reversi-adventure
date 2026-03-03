# Self-Retrospective Not Triggered Without Explicit Skill Invocation

## Summary

The AI does not perform self-retrospective (reviewing findings, logging issues, updating CLAUDE.md) after completing significant tasks unless the user explicitly invokes `/post-task-review`. This means important learnings and architectural debt can be silently lost.

## Problem

In Phase 2 implementation, the AI:
- Encountered and fixed multiple clippy issues, type mismatches, and API deprecations
- Did not proactively log these as lessons or issues
- Only performed review when the user explicitly ran `/post-task-review`
- When the review did run, it used `gh issue create` instead of `docs/issues/` (violating the project workflow)

The self-retrospective should be a natural part of the workflow's completion step, not a separate skill the user must remember to invoke.

## Proposed Solution

1. Migrate `post-task-review` from user-level skill to project-level skill in `.claude/skills/`
2. Adjust the skill to:
   - Use `docs/issues/` as the primary issue tracking location (align with AI-Centered Development workflow)
   - Optionally mirror to GitHub issues with user approval
   - Include lessons.md updates as part of the review
3. Integrate the review into the existing workflow: after moving a plan from `todo/` to `done/`, the AI should automatically perform a retrospective before creating a PR

## Priority

Medium — process gap that causes knowledge loss between sessions.
