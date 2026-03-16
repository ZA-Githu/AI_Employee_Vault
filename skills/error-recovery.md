---
title: "Skill: Error Recovery"
id: skill-error-recovery
version: 1.0.0
tier: Gold
tags: [skill, error, recovery, degradation, gold]
---

# Skill: Error Recovery
**ID:** skill-error-recovery
**Version:** 1.0.0
**Tier:** Gold
**Trigger:** Automatic — called by any skill on failure | `recover <skill>` | `check errors`

## Description

Classifies errors by severity (L1–L4), applies the appropriate recovery strategy, and escalates to human when automatic recovery is not possible. Ensures graceful degradation — a failing Gold-tier capability never silently stops the entire system. Every recovery attempt and escalation is logged. This skill is called internally by all other Gold skills and the Ralph Wiggum Loop.

## Error Levels

| Level | Name | Examples | Auto-Recoverable |
|-------|------|---------|-----------------|
| **L1** | Transient | Network timeout, API rate limit (429), DNS failure | Yes — retry 2× |
| **L2** | Recoverable | File not found, wrong format, missing frontmatter field | Yes — auto-fix if possible |
| **L3** | Escalatable | OAuth auth failure, permission denied, session expired | No — alert human |
| **L4** | Critical | Data corruption, loop abort, vault structure broken | No — halt + alert |

## Inputs

- `error` (object, required): Error details from the calling skill
  - `skill` (string): Skill that raised the error
  - `message` (string): Error message
  - `level` (string): `L1 | L2 | L3 | L4`
  - `context` (object): Any relevant state (file path, step number, etc.)
- `retry_count` (integer, optional): How many times this error has already been retried

## Outputs

- Recovery action taken (retry / auto-fix / escalate / halt)
- Calling skill resumes or is paused
- Log entry: `RECOVER` or `ESCALATE`

## Steps by Error Level

### L1 — Transient
1. Log `RECOVER` with retry count.
2. Wait 30 seconds.
3. Retry the failed operation.
4. If retry succeeds: log ✅, return control to calling skill.
5. If retry fails (2nd attempt): escalate to L3 handling.

### L2 — Recoverable
1. Log `RECOVER` with auto-fix description.
2. Attempt automatic fix:
   - File not found → create from template if applicable
   - Wrong format → reformat and re-validate
   - Missing frontmatter → inject required fields with defaults
3. If fix succeeds: retry original operation. Log ✅.
4. If fix fails: escalate to L3 handling.

### L3 — Escalatable
1. Log `ESCALATE` with full error context.
2. Pause the calling skill (do not halt the entire system).
3. Write an escalation note to `Needs_Action/`:
   ```yaml
   type: escalation
   skill: <skill name>
   error: <error message>
   action_required: "Human must resolve auth/permission issue"
   ```
4. Alert human in the next session.
5. Other skills continue running — graceful degradation.

### L4 — Critical
1. Log `ESCALATE` with level: CRITICAL.
2. Halt the calling skill AND the Ralph Wiggum Loop if active.
3. Write escalation note to `Needs_Action/` with `priority: critical`.
4. Attempt to preserve loop state if Ralph Wiggum was running.
5. Alert human immediately (via vault log + Dashboard.md update).
6. No other destructive actions.

## Graceful Degradation Map

| Failing Capability | Degraded Behaviour |
|--------------------|-------------------|
| LinkedIn posting | Log ERROR → move plan to `Needs_Action/` for retry |
| Twitter posting | Log ERROR → leave in `Approved/` for retry |
| Gmail API | Log WARNING → skip email processing cycle → retry next poll |
| WhatsApp watcher | Log ERROR → fall back to filesystem_watcher only |
| Weekly audit | Log ERROR → generate partial briefing → mark incomplete |
| Ralph Wiggum Loop step | Save state → escalate → allow manual resume |
| CEO Briefing | Log ERROR → write empty template briefing → mark for human completion |

## Acceptance Criteria

- [ ] L1 errors retried automatically (max 2 times, 30s apart)
- [ ] L2 errors auto-fixed where possible before retry
- [ ] L3 errors pause the affected skill without halting the system
- [ ] L4 errors halt the loop and alert human via Dashboard.md
- [ ] Every recovery attempt logged with `RECOVER`
- [ ] Every escalation creates a `Needs_Action/` note
- [ ] System continues running for all unaffected skills after L3 escalation

## Constraints

- MUST NOT swallow errors silently — every error must produce a log entry
- MUST NOT retry L3/L4 errors automatically
- MUST NOT delete vault files as part of error recovery
- MUST NOT mark an escalated item as resolved without human confirmation
- MUST preserve Ralph Wiggum Loop state on error

## Log Requirement

```
- `HH:MM:SS` | **RECOVER** | `skill/twitter-post` → `retry/1` | ✅ | error: timeout | action: retry after 30s
- `HH:MM:SS` | **RECOVER** | `skill/twitter-post` → `retry/2` | ❌ | error: timeout | escalating to L3
- `HH:MM:SS` | **ESCALATE** | `skill/twitter-post` → `Needs_Action/escalation.md` | ❌ | level: L3 | reason: auth failed
- `HH:MM:SS` | **ESCALATE** | `loop/ceo-briefing` → `Needs_Action/critical.md` | ❌ | level: L4 | reason: vault corruption
```
