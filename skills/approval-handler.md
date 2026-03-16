---
title: "Skill: Approval Handler"
id: skill-approval-handler
version: 1.0.0
tier: Silver
tags: [skill, approval, workflow, silver]
---

# Skill: Approval Handler
**ID:** skill-approval-handler
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Manual — user says "approve plan <filename>", "reject plan <filename>", or "recall plan <filename>"

## Description

Handles the human's approval decision on any plan in `Pending_Approval/`. When the human approves, the skill stamps the frontmatter and moves the plan to `Approved/`. When the human rejects, the skill collects a rejection reason and moves the plan to `Rejected/`. When the human recalls a plan, it moves back to `Plans/` for revision. Every transition is logged. This skill is the gatekeeper of the entire Silver Tier approval pipeline.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Approve plan | `approve plan <filename>` | Stamp approval and move to Approved/ |
| Reject plan | `reject plan <filename>` | Record rejection reason and move to Rejected/ |
| Recall plan | `recall plan <filename>` | Return plan to Plans/ for revision |
| List pending | `what needs approval?` | Show all plans in Pending_Approval/ with age |
| Show plan | `show plan <filename>` | Display plan content for review |
| Approval history | `approval history` | List all approved and rejected plans this month |

## Inputs

- `operation` (string, required): One of `approve | reject | recall | list | show | history`
- `filename` (string, required for approve/reject/recall/show): Name of the plan in `Pending_Approval/`
- `rejection_reason` (string, required for reject): Human's reason for rejection — must be non-empty
- `approval_note` (string, optional for approve): Optional note from the human to guide execution

## Outputs

- **approve:** Plan in `Approved/` with stamped frontmatter, log entry `PLAN_APPROVE`
- **reject:** Plan in `Rejected/` with rejection reason, log entry `PLAN_REJECT`
- **recall:** Plan returned to `Plans/` with `status: draft`, log entry `PLAN_RECALL`
- **list:** Formatted list of all pending plans with submission date and age
- **show:** Full plan content printed for human review
- **history:** Table of all approval decisions this month

## Steps

### Approve

1. Validate `Pending_Approval/<filename>.md` exists. If not, log `ERROR` and abort.
2. Read the plan and confirm `status: pending-approval`.
3. **Update frontmatter:**
   - `status: approved`
   - `approved_by: human`
   - `approved_date: YYYY-MM-DD`
   - `approval_note: "<text>"` (if provided)
4. Determine destination: `Approved/<filename>.md` (create `Approved/` if missing).
5. Write updated plan to `Approved/<filename>.md`.
6. Delete source from `Pending_Approval/`.
7. Log `PLAN_APPROVE`.
8. Confirm to user: "Plan approved. Say `execute plan <filename>` to begin, or `execute approved plans` to run the full queue."

### Reject

1. Validate `Pending_Approval/<filename>.md` exists. If not, log `ERROR` and abort.
2. **Require rejection reason.** If `rejection_reason` is empty or missing, prompt the human before proceeding.
3. Read the plan and confirm `status: pending-approval`.
4. **Update frontmatter:**
   - `status: rejected`
   - `rejected_by: human`
   - `rejected_date: YYYY-MM-DD`
   - `rejection_reason: "<reason>"`
5. Determine destination: `Rejected/<filename>.md`.
6. Write updated plan to `Rejected/<filename>.md`.
7. Delete source from `Pending_Approval/`.
8. Log `PLAN_REJECT`.
9. Confirm to user: "Plan rejected and archived. The agent will read this rejection reason at next session start."

### Recall

1. Validate `Pending_Approval/<filename>.md` exists. If not, log `ERROR` and abort.
2. Read the plan.
3. **Update frontmatter:**
   - `status: draft`
   - Remove `submitted:` and `awaiting_review_by:` fields
   - Add `recalled_date: YYYY-MM-DD`
4. Write updated plan back to `Plans/<filename>.md`.
5. Delete source from `Pending_Approval/`.
6. Log `PLAN_RECALL`.
7. Confirm to user: "Plan recalled to Plans/. Edit and re-submit when ready."

### List Pending

1. List all `.md` files in `Pending_Approval/`.
2. For each file, read `submitted:` and calculate age in hours.
3. Print formatted list:
   ```
   ⏳ PENDING APPROVAL
   ─────────────────────────────────────────────
   1. <filename>
      Submitted: YYYY-MM-DD  |  Age: Xh  [⚠️ STALE] (if 48h+)
      Priority: <priority>   |  Type: <type>
   ```
4. If list is empty: "No plans awaiting approval."

## Acceptance Criteria

- [ ] Approve stamps `approved_by: human` and `approved_date:` before moving
- [ ] Reject refuses to proceed if `rejection_reason` is empty
- [ ] Recall resets `status` to `draft` and removes submission fields
- [ ] Source file is deleted from `Pending_Approval/` after every transition
- [ ] Every operation produces a correctly typed log entry
- [ ] List shows age in hours and flags stale plans (48h+)

## Constraints

- MUST NOT approve a plan on behalf of the human — `approved_by` is always `human`
- MUST NOT reject without a non-empty `rejection_reason`
- MUST NOT move plans to `Approved/` or `Rejected/` unless source is in `Pending_Approval/`
- MUST NOT execute any plan — execution is handled by `check-approvals` skill
- MUST NOT modify the body content of plans — frontmatter updates only
- MUST require explicit human command for every approval or rejection decision

## Error Cases

| Error | Response |
|-------|----------|
| File not in Pending_Approval/ | Log ERROR, inform human, suggest `what needs approval?` |
| Plan status is not pending-approval | Log ERROR, abort — plan may have already been decided |
| Empty rejection reason | Prompt human for reason, do not proceed |
| Destination file already exists | Append `-v2` suffix, warn human of duplicate |
| Approved/ or Rejected/ folder missing | Create folder, log CREATE, then proceed |

## Log Requirements

**Approve:**
```
- `HH:MM:SS` | **PLAN_APPROVE** | `Pending_Approval/<filename>.md` → `Approved/<filename>.md` | ✅ success | approved by human
```
**Reject:**
```
- `HH:MM:SS` | **PLAN_REJECT** | `Pending_Approval/<filename>.md` → `Rejected/<filename>.md` | ✅ success | reason: <rejection_reason>
```
**Recall:**
```
- `HH:MM:SS` | **PLAN_RECALL** | `Pending_Approval/<filename>.md` → `Plans/<filename>.md` | ✅ success | recalled for revision
```
