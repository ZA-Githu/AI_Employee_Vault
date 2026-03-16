---
title: "Skill: Create Plan"
id: skill-create-plan
version: 1.0.0
tier: Silver
tags: [skill, plan, silver]
---

# Skill: Create Plan
**ID:** skill-create-plan
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Manual — user says "create plan <title>" or "draft plan <title>"

## Description

Creates a new structured plan file inside `Plans/` using the Silver Plan Template (`Plan-Template.md`). Before writing a single line, the agent works through the Claude Reasoning Loop (Section 3 of the template) to think through what it knows, what it assumes, what constraints apply, and which approach is best. The resulting plan is a complete, reviewable document ready for human approval.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Create general plan | `create plan <title>` | Draft a plan for any task or project |
| Create LinkedIn post | `draft linkedin post <topic>` | Draft a LinkedIn post as a plan |
| Create from task | `plan task <filename>` | Turn a Needs_Action note into a plan |

## Inputs

- `title` (string, required): The plan title — becomes the filename and `title:` field
- `type` (string, optional, default `plan`): One of `plan | linkedin-post`
- `priority` (string, optional, default `medium`): `low | medium | high | critical`
- `context` (string, optional): Any background information the agent should factor into the reasoning loop

## Outputs

- New `.md` file in `Plans/` named `YYYY-MM-DD — <Title>.md`
- File uses the Silver Plan Template with all sections populated
- One log entry written via `PLAN_CREATE`

## Steps

1. **Read constitutions.** Re-read `Bronze-Constitution.md` Section 3 and `Silver-Constitution.md` Section 4–6 before starting.
2. **Read Plan-Template.md.** Load the full template from vault root.
3. **Work through the Reasoning Loop (Section 3):**
   - List what is known from context and vault files
   - Identify assumptions that need human confirmation
   - Note all applicable constraints from both constitutions
   - Generate at least 2 options and evaluate pros/cons
   - Select the best option and justify the choice
4. **Populate all template sections** using the reasoning loop output.
5. **Set frontmatter:**
   - `title`: from input
   - `type`: from input (`plan` or `linkedin-post`)
   - `status: draft`
   - `priority`: from input
   - `created`: today's date
   - `author: claude`
6. **Determine filename:** `YYYY-MM-DD — <Kebab-Case-Title>.md`
7. **Check for filename collision** in `Plans/` — append `-v2`, `-v3` if needed.
8. **Write the file** to `Plans/`.
9. **Log** with action type `PLAN_CREATE`.
10. **Confirm to user:** file path, title, next step (`submit plan <filename>` when ready).

## Acceptance Criteria

- [ ] File exists in `Plans/` with correct naming convention
- [ ] All 12 template sections are present (remove only explicitly inapplicable ones)
- [ ] Reasoning Loop (Section 3) is fully populated — not left as placeholder text
- [ ] Frontmatter has `status: draft`, `author: claude`, valid `created:` date
- [ ] Log entry with `PLAN_CREATE` exists in today's log
- [ ] Agent confirms file path and suggests next step to user

## Constraints

- MUST NOT create plan files anywhere except `Plans/`
- MUST NOT skip the Reasoning Loop — it must be populated before writing the plan
- MUST NOT set `status` to anything other than `draft` at creation
- MUST NOT submit the plan — submission is a separate skill (`submit-for-approval`)
- MUST NOT create a plan for an action that is already `Approved/` — check first

## Log Requirement

```
- `HH:MM:SS` | **PLAN_CREATE** | — → `Plans/<filename>.md` | ✅ success | title: <plan title>
```
