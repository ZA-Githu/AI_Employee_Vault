---
title: "Skill: Ralph Wiggum Loop"
id: skill-ralph-wiggum
version: 1.0.0
tier: Gold
tags: [skill, loop, autonomous, multi-step, stop-hook, cross-domain, gold]
---

# Skill: Ralph Wiggum Loop
**ID:** skill-ralph-wiggum
**Version:** 1.0.0
**Tier:** Gold
**Trigger:**
- `run loop <plan_file>` | `execute plan <plan_file>`
- `resume loop <state_file>`
- Auto-triggered internally after a plan is moved to `Approved/`

## Description

The Ralph Wiggum Loop is Gold Tier's autonomous multi-step execution engine. It decomposes an approved plan into atomic steps, executes them one by one, checks the outcome after each step, and keeps going until the entire task lands in `Done/` — or a hard-stop condition fires. Named for its "I just do things" character: it acts repeatedly until the job is truly done.

The loop includes a **stop-hook pattern**: before every step, it checks a defined set of halt conditions. Any hard-stop condition instantly pauses the loop, preserves state, and escalates to the human.

Supports **cross-domain tasks** — a single loop can complete steps that span personal (email, WhatsApp) and business (social media, accounting) domains.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Execute approved plan | `run loop <filename>` | Run all steps of an approved plan |
| Resume paused loop | `resume loop <state_file>` | Continue from last checkpoint |
| Single step | `run step <N> of <plan>` | Execute one specific step manually |
| Preview steps | `preview loop <filename>` | List steps without executing |
| Status check | `loop status` | Show active and paused loops |

---

## Inputs

- `plan_file` (string, required): Filename in `Approved/` — must have `approved_by: human`
- `resume_from` (integer, optional): Step number to start from (used in resume mode)
- `domain` (string, optional): `personal | business | all` filter for step routing
- `dry_run` (boolean, optional): Parse and plan only, execute nothing

---

## Outputs

- All steps executed in sequence
- Each step logged with `LOOP_STEP`
- Loop state file in `Plans/` updated after each step
- On success: completion note in `Done/YYYY-MM/`, plan frontmatter updated, loop state deleted
- On abort: loop state preserved in `Plans/`, plan moved to `Needs_Action/` with `status: blocked`
- Log entries: `LOOP_START`, `LOOP_STEP` (×N), `LOOP_COMPLETE` or `LOOP_ABORT`

---

## Stop-Hook Pattern

Before executing **every step**, the loop runs the stop-hook check:

```
STOP-HOOK (runs before each step)
  ├─ Is plan still in Approved/? If not → ABORT (plan recalled)
  ├─ Is this step destructive (delete/publish/send)? If yes → check Approved/ entry
  ├─ Have 3 consecutive steps failed? If yes → ABORT
  ├─ Has the loop been running > 30 minutes? If yes → PAUSE + alert
  ├─ Is there a human "stop/halt/abort" message? If yes → ABORT immediately
  └─ Is this step in the wrong domain? If yes → skip + log SKIP
```

If all checks pass → execute the step.

---

## Hard Stop Conditions

| Condition | Response |
|-----------|----------|
| Plan removed from `Approved/` mid-loop | LOOP_ABORT immediately |
| Step requires unapproved external action | Pause, submit sub-plan, wait for approval |
| Step is destructive without `Approved/` entry | Halt, require explicit human confirmation |
| 3 consecutive step failures | LOOP_ABORT, alert human |
| Loop running > 30 minutes | PAUSE, checkpoint, alert human |
| Human message: "stop" / "halt" / "abort" | Immediate LOOP_ABORT, preserve state |
| `error-recovery.md` returns L4 (Critical) | Full LOOP_ABORT |

---

## Steps (Execution Flow)

1. **Validate plan.** Confirm `Approved/<plan_file>.md` exists with `approved_by: human`. Parse `## Proposed Actions` into numbered atomic steps.
2. **Log LOOP_START.** Record step count, plan title, trigger source, timestamp.
3. **Determine resume point.** If `resume_from` is set, skip already-completed steps.
4. **For each step N (from resume_from or 1):**
   a. Run stop-hook check (all conditions above).
   b. Log `LOOP_STEP` — step N, description, domain tag.
   c. Identify which skill handles this step (social-poster, weekly-audit, gmail-watcher, etc.).
   d. Invoke that skill.
   e. Check outcome:
      - ✅ Success → update loop state file → advance to N+1
      - ❌ Failure → call `skills/error-recovery.md`
        - L1/L2 recovered → retry step → continue
        - L3/L4 or not recovered → log LOOP_ABORT → halt
5. **On all steps complete:**
   - Log `LOOP_COMPLETE`
   - Write completion note to `Done/YYYY-MM/`
   - Update plan frontmatter: `status: completed`, `completed: YYYY-MM-DD`
   - Delete loop state file from `Plans/`
6. **On abort:**
   - Log `LOOP_ABORT` with reason
   - Preserve loop state file in `Plans/`
   - Move plan to `Needs_Action/` with `status: blocked`, `blocked_reason: <reason>`

---

## Loop State File (Written After Each Step)

```yaml
---
title: "Loop State: <plan title>"
type: loop-state
parent_plan: "<Approved/filename.md>"
steps_total: N
last_step_completed: N
status: running | paused | aborted
reason: ""
resume_from: N+1
started_at: "YYYY-MM-DD HH:MM:SS"
domain: personal | business | all
---

## Completed Steps

1. ✅ Step description — completed at HH:MM:SS
2. ✅ Step description — completed at HH:MM:SS
3. ❌ Step description — failed, loop aborted

## Next Step

N+1. Step description
```

---

## Cross-Domain Support

The loop handles tasks that span **personal** and **business** domains in the same execution:

```
Example: "Post LinkedIn update AND send CEO briefing email AND log to Accounting"
  Step 1 (business): Post to LinkedIn — uses skills/linkedin-poster.md
  Step 2 (personal): Send summary email — uses watcher/gmail_watcher.py via email skill
  Step 3 (business): Write Accounting entry — uses skills/weekly-audit.md
```

Domain is tagged on each step using the plan's frontmatter and step-level `#personal` or `#business` tags. Cross-domain steps execute sequentially — no parallel execution.

---

## Acceptance Criteria

- [ ] Loop only starts from `Approved/` plans with `approved_by: human`
- [ ] Stop-hook runs before every step
- [ ] Every step logged with `LOOP_STEP` regardless of outcome
- [ ] Loop state file written after every step (not just at end)
- [ ] Hard-stop conditions halt the loop reliably
- [ ] State preserved on abort — loop resumes from correct step
- [ ] Completion note written to `Done/` on success
- [ ] `LOOP_ABORT` always includes human-readable reason

## Constraints

- MUST NOT auto-approve sub-tasks requiring external actions
- MUST NOT continue past 3 consecutive failures
- MUST NOT run > 30 minutes without a checkpoint
- MUST NOT modify plan content in `Approved/` during execution
- MUST NOT execute steps in parallel — always sequential
- MUST log every step regardless of outcome

## Related Skills

- `skills/error-recovery.md` — called on every step failure
- `skills/audit-logger.md` — records loop events as JSON audit entries
- `skills/social-poster.md` — invoked for social media steps
- `skills/weekly-audit.md` — invoked for audit/briefing steps
- `skills/cross-domain-integrator.md` — routes steps to correct domain

## Log Requirement

```
- `HH:MM:SS` | **LOOP_START** | `Approved/plan.md` → — | ✅ | steps: 4 | domain: all
- `HH:MM:SS` | **LOOP_STEP** | `step/1` → `step/2` | ✅ | action: posted to Twitter | domain: business
- `HH:MM:SS` | **LOOP_STEP** | `step/2` → — | ❌ | action: send email | error: gmail timeout
- `HH:MM:SS` | **LOOP_ABORT** | `Approved/plan.md` → `Needs_Action/` | ❌ | reason: 3 consecutive failures
- `HH:MM:SS` | **LOOP_COMPLETE** | `Approved/plan.md` → `Done/2026-02/` | ✅ | steps: 4/4 | duration: 3m 22s
```
