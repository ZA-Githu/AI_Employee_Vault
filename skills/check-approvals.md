---
title: "Skill: Check Approvals"
id: skill-check-approvals
version: 1.0.0
tier: Silver
tags: [skill, approval, execution, silver]
---

# Skill: Check Approvals
**ID:** skill-check-approvals
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Auto — runs at session start. Manual — user says "check approvals" or "execute approved plans"

## Description

Reads `Pending_Approval/` and `Approved/` at session start to give the human a complete picture of the approval pipeline. For plans in `Pending_Approval/` that are older than 48 hours, the agent surfaces an urgent alert. For plans in `Approved/` that have not yet been executed, the agent queues them for execution in priority order and begins working through the queue.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Session check | Auto at session start | Report full approval pipeline status |
| Manual check | `check approvals` | Same report on demand |
| Execute queue | `execute approved plans` | Begin executing all approved, unexecuted plans |
| Execute single | `execute plan <filename>` | Execute one specific approved plan |
| Stale alert | Auto | Alert if any plan has been in Pending_Approval/ for 48+ hours |
| Read rejections | Auto at session start | Read Rejected/ notes and log lessons learned |

## Inputs

- `mode` (string, optional, default `report`): One of `report | execute | single`
- `filename` (string, required for single mode): Name of the approved plan to execute

## Outputs

- **report mode:** Formatted summary of all pipeline states, stale alerts, execution queue
- **execute mode:** Execution of each approved plan in priority order, with per-step log entries
- **single mode:** Execution of one specific approved plan

## Steps

### Session Start Report

1. **Scan Pending_Approval/.** List all files with their `submitted:` date.
   - For each file older than 48 hours: flag as `⚠️ STALE — needs review`
2. **Scan Approved/.** List all files not yet marked as executed.
   - Sort by `priority:` (critical → high → medium → low)
3. **Scan Rejected/.** Read `rejection_reason:` from each file added since last session.
   - Summarise lessons learned in one bullet per rejection.
4. **Print pipeline report** to the user (see format below).
5. **Log** with action type `SKILL_RUN`.

### Execute Approved Plans

1. **Read the approved plan** from `Approved/`.
2. **Validate plan** — confirm `status: approved` and `approved_by:` is present.
3. **Work through Proposed Actions** (Section 4 of the plan) step by step:
   - For each step, perform the action using the appropriate Bronze or Silver skill
   - Log each action with its relevant action type
   - If a step requires human input, pause and surface the question
4. **On completion:**
   - Add `executed: YYYY-MM-DD` and `execution_status: complete` to frontmatter
   - Append a Completion Summary to the plan body
   - Move the plan to `Done/YYYY-MM/`
   - Log with action type `PLAN_EXECUTE`
5. **If a step fails:**
   - Log `ERROR` with full details
   - Mark the plan `execution_status: blocked`
   - Alert the human with the blocker and suggested next step
   - Do not continue to the next step

### Pipeline Report Format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  APPROVAL PIPELINE — YYYY-MM-DD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏳ PENDING APPROVAL (N)
  • <filename> — submitted YYYY-MM-DD [X days ago] [⚠️ STALE if 48h+]

✅ APPROVED & READY TO EXECUTE (N)
  • [CRITICAL] <filename>
  • [HIGH]     <filename>
  • [MEDIUM]   <filename>

❌ RECENTLY REJECTED (N)
  • <filename> — reason: <rejection_reason>

📋 LESSONS FROM REJECTIONS
  • <one bullet per rejected plan>

▶  Next: say "execute approved plans" to begin execution queue
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Acceptance Criteria

- [ ] Session-start report runs automatically before any other action
- [ ] Stale plans (48h+) are flagged with `⚠️ STALE` in the report
- [ ] Approved plans are sorted by priority before execution
- [ ] Each execution step is logged individually
- [ ] Completed plans are moved to `Done/YYYY-MM/` with execution summary
- [ ] Rejection reasons are read and surfaced as lessons
- [ ] Agent pauses and surfaces blockers rather than skipping failed steps

## Constraints

- MUST NOT execute a plan that is not in `Approved/` with `approved_by:` set
- MUST NOT skip a step in the Proposed Actions — either complete it or report a blocker
- MUST NOT mark a plan as complete if any step is unresolved
- MUST NOT modify the human's approval decision or rejection reason
- MUST check `Pending_Approval/` before `Approved/` — always surface what needs the human first
- MUST read `Rejected/` at session start — rejection lessons inform future plan quality

## Error Cases

| Error | Response |
|-------|----------|
| Approved plan missing `approved_by:` | Log `ERROR`, skip execution, alert human |
| Execution step fails | Log `ERROR`, mark `execution_status: blocked`, pause and alert |
| Plan already executed | Skip silently, note in report |
| Pending_Approval/ empty | Report "No plans awaiting approval" |
| Approved/ empty | Report "No approved plans ready to execute" |

## Log Requirements

**Session start scan:**
```
- `HH:MM:SS` | **SKILL_RUN** | `.claude/skills/check-approvals.md` | pipeline scanned: pending=N approved=N rejected=N | ✅ success
```

**Stale alert:**
```
- `HH:MM:SS` | **SKILL_RUN** | `Pending_Approval/<filename>.md` | ⚠️ stale — N days in pending approval | ✅ flagged
```

**Plan execution complete:**
```
- `HH:MM:SS` | **PLAN_EXECUTE** | `Approved/<filename>.md` → `Done/YYYY-MM/<filename>.md` | ✅ success | all steps completed
```
