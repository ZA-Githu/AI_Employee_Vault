---
title: "Skill: Submit for Approval"
id: skill-submit-for-approval
version: 1.0.0
tier: Silver
tags: [skill, approval, silver]
---

# Skill: Submit for Approval
**ID:** skill-submit-for-approval
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Manual — user says "submit plan <filename>" or "submit for approval <filename>"

## Description

Moves a plan from `Plans/` to `Pending_Approval/`, updates its frontmatter to `status: pending-approval`, adds the `submitted:` date, and alerts the human that a plan is ready for their review. This skill enforces the approval gate: nothing moves forward without passing through this step first.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Submit single plan | `submit plan <filename>` | Move one plan to Pending_Approval/ |
| List submittable plans | `list drafts` | Show all plans in Plans/ that are ready to submit |
| Check pending queue | `what needs approval?` | Show all files in Pending_Approval/ with age |

## Inputs

- `filename` (string, required): Name of the plan file in `Plans/` to submit
- `note_to_reviewer` (string, optional): A short message to add for the human reviewer

## Outputs

- Plan moved from `Plans/<filename>.md` to `Pending_Approval/<filename>.md`
- Frontmatter updated: `status: pending-approval`, `submitted: YYYY-MM-DD`
- Human notified with a clear summary of what needs their decision
- One log entry written with action type `PLAN_SUBMIT`

## Steps

1. **Validate source.** Confirm `Plans/<filename>.md` exists. If not, log `ERROR` and abort.
2. **Read the plan.** Load full content and parse frontmatter.
3. **Check plan is complete:**
   - `status` must be `draft`
   - `title:` must be non-empty
   - Reasoning Loop (Section 3) must not contain placeholder text
   - If any check fails: report to human, do not submit
4. **Update frontmatter:**
   - Set `status: pending-approval`
   - Add `submitted: YYYY-MM-DD`
   - Add `awaiting_review_by: human`
   - If `note_to_reviewer` provided, add `reviewer_note: "<text>"`
5. **Write updated content** to `Pending_Approval/<filename>.md`
6. **Delete** source file from `Plans/`
7. **Log** with action type `PLAN_SUBMIT`
8. **Alert human** with a structured summary:
   - Plan title and filename
   - Priority level
   - One-line objective
   - List of questions from Section 9 of the plan
   - Reminder: `approve plan <filename>` or `reject plan <filename>`

## Acceptance Criteria

- [ ] Source file no longer exists in `Plans/`
- [ ] File exists in `Pending_Approval/` with the same filename
- [ ] `status: pending-approval` is set in frontmatter
- [ ] `submitted:` field is present with today's date
- [ ] Human receives a clear approval-request summary
- [ ] Log entry with `PLAN_SUBMIT` exists in today's log

## Constraints

- MUST NOT submit a plan that still has placeholder text in the Reasoning Loop
- MUST NOT submit a plan with `status` other than `draft`
- MUST NOT move files to `Approved/` or `Rejected/` — those are human actions
- MUST NOT submit more than one version of the same plan title simultaneously
- MUST abort and report if source file is not found in `Plans/`

## Error Cases

| Error | Response |
|-------|----------|
| File not in Plans/ | Log `ERROR`, inform human, abort |
| Plan has placeholder text | List incomplete sections, ask human if they want to force-submit |
| Plan already in Pending_Approval/ | Inform human, do not duplicate |
| Title is empty | Prompt human to add a title before submitting |

## Log Requirement

```
- `HH:MM:SS` | **PLAN_SUBMIT** | `Plans/<filename>.md` → `Pending_Approval/<filename>.md` | ✅ success | awaiting human approval
```
