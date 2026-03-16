---
title: "Skill: Audit Logger"
id: skill-audit-logger
version: 1.0.0
tier: Gold
tags: [skill, logging, audit, json, error-recovery, gold]
---

# Skill: Audit Logger
**ID:** skill-audit-logger
**Version:** 1.0.0
**Tier:** Gold
**Trigger:**
- Auto — called internally by every Gold skill after each action
- Manual: `show audit log` | `check errors today` | `audit log for <date>`
- `recovery status` | `list escalations`

## Description

Comprehensive JSON audit logging for all Gold Tier actions, errors, and approvals. Writes a structured JSON log file alongside the existing Markdown log (`Logs/YYYY-MM-DD.json`) so that audit data can be queried, filtered, and analysed programmatically. Also provides the shared error recovery helpers that other skills call when an operation fails — classifying errors by level and applying the correct recovery strategy.

Every Gold skill must call this skill to log its actions. This is the single source of truth for machine-readable audit history.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Log action | Called by skills internally | Write JSON entry to `Logs/YYYY-MM-DD.json` |
| Log error | Called on failure | Write error entry with level + recovery action |
| Log approval | Called on plan state change | Write approval/rejection event |
| View today's log | `show audit log` | Display today's JSON log as formatted table |
| View errors | `check errors today` | Filter log for ERROR and ESCALATE entries |
| View log by date | `audit log for YYYY-MM-DD` | Display specific day's log |
| Recovery status | `recovery status` | List active escalations in `Needs_Action/` |
| Error summary | `error summary this week` | Count and group errors by skill for the week |

---

## Inputs

### Log Entry (called by other skills)
- `action_type` (string, required): The action type (see Action Types table)
- `skill` (string, required): Name of the calling skill
- `source` (string, required): Source path or resource
- `destination` (string, optional): Destination path (or `null`)
- `outcome` (string, required): `success` | `failed` | `skipped` | `escalated`
- `notes` (string, optional): Human-readable description
- `error` (object, optional): Error details for failed entries
  - `message` (string): Error message
  - `level` (string): `L1` | `L2` | `L3` | `L4`
  - `traceback` (string, optional): Stack trace if available

### Recovery Helper (called by other skills on failure)
- `error` (object, required): Error from the failing operation
- `retry_count` (integer, optional): Times already retried (default: 0)
- `calling_skill` (string, required): Skill requesting recovery

---

## Outputs

### Log Entry Output
- Entry written to `Logs/YYYY-MM-DD.json` (appended)
- Entry written to `Logs/YYYY-MM-DD.md` (appended — Bronze format)
- Returns the written entry as confirmation

### Recovery Helper Output
- Recovery action taken: `retry` | `auto_fix` | `escalate` | `halt`
- If escalation: `Needs_Action/YYYY-MM-DD HH-MM — Escalation-<skill>.md` created
- If L4: `Dashboard.md` updated with critical alert
- Returns outcome and next action for the calling skill

---

## JSON Log Schema

Each entry in `Logs/YYYY-MM-DD.json` follows this schema:

```json
{
  "timestamp": "2026-02-25T14:32:01",
  "action_type": "SOCIAL_POST",
  "skill": "social-poster",
  "source": "Approved/2026-02-25-tweet.md",
  "destination": "Done/2026-02/2026-02-25-tweet.md",
  "outcome": "success",
  "notes": "platform: twitter | url: https://x.com/...",
  "error": null,
  "session_id": "2026-02-25-session-1",
  "tier": "gold"
}
```

Error entry example:
```json
{
  "timestamp": "2026-02-25T14:35:12",
  "action_type": "ERROR",
  "skill": "social-poster",
  "source": "Approved/2026-02-25-fb-post.md",
  "destination": null,
  "outcome": "failed",
  "notes": "Facebook browser session expired",
  "error": {
    "message": "Playwright: Target page closed",
    "level": "L3",
    "recovery_action": "escalated",
    "retry_count": 2
  },
  "session_id": "2026-02-25-session-1",
  "tier": "gold"
}
```

---

## Action Types (Full Gold Tier Reference)

| Action Type | Used By | Description |
|------------|---------|-------------|
| `CREATE` | Any | File created in vault |
| `MOVE` | Any | File moved between folders |
| `EDIT` | Any | File content modified |
| `DELETE` | Any | File deleted (must log reason) |
| `SKILL_RUN` | Any | Skill invoked |
| `TRIAGE` | filesystem-watcher | Inbox item triaged |
| `CLOSE` | close-task | Task moved to Done/ |
| `ERROR` | Any | Operation failed |
| `PLAN_CREATE` | create-plan | New draft in Plans/ |
| `PLAN_SUBMIT` | submit-for-approval | Plan moved to Pending_Approval/ |
| `PLAN_APPROVE` | approval-handler | Plan approved by human |
| `PLAN_REJECT` | approval-handler | Plan rejected by human |
| `PLAN_EXECUTE` | ralph-wiggum | Plan execution started |
| `LOOP_START` | ralph-wiggum | Loop begins |
| `LOOP_STEP` | ralph-wiggum | Single loop step |
| `LOOP_COMPLETE` | ralph-wiggum | Loop finished all steps |
| `LOOP_ABORT` | ralph-wiggum | Loop halted |
| `SOCIAL_POST` | social-poster | Post published to platform |
| `SOCIAL_SUMMARY` | social-poster | Weekly social summary generated |
| `AUDIT_RUN` | weekly-audit | Weekly audit executed |
| `BRIEFING_GEN` | weekly-audit | CEO Briefing generated |
| `RECOVER` | audit-logger | Error recovery attempted |
| `ESCALATE` | audit-logger | Issue escalated to human |
| `MCP_CALL` | Any MCP | MCP server invoked |

---

## Error Recovery Helper

When called by another skill with an error, this helper:

### L1 — Transient (Network, Rate Limit)
1. Log `RECOVER` with `retry_count`.
2. Return `{ action: "retry", wait_seconds: 30 }` to calling skill.
3. If `retry_count >= 2` → escalate to L3.

### L2 — Recoverable (File/Format Issues)
1. Attempt auto-fix (create missing file from template, fix frontmatter).
2. Log `RECOVER` with auto-fix description.
3. Return `{ action: "retry_after_fix" }` to calling skill.
4. If fix fails → escalate to L3.

### L3 — Escalatable (Auth, Permissions)
1. Log `ESCALATE` with full error context.
2. Create `Needs_Action/YYYY-MM-DD HH-MM — Escalation-<skill>.md`:
   ```yaml
   ---
   title: "Escalation: <skill> — <error summary>"
   type: escalation
   skill: <skill>
   error_level: L3
   error: "<message>"
   action_required: "Human must resolve: <guidance>"
   status: pending
   priority: high
   created: YYYY-MM-DD
   ---
   ```
3. Return `{ action: "pause_skill" }` — other skills continue running.

### L4 — Critical
1. Log `ESCALATE` with level CRITICAL.
2. Create `Needs_Action/` escalation note with `priority: critical`.
3. Update `Dashboard.md` with critical alert line.
4. Return `{ action: "halt_loop" }` to ralph-wiggum.

---

## Graceful Degradation Map

| Failing Capability | Degraded Behaviour |
|--------------------|-------------------|
| JSON log write fails | Fall back to Markdown log only. Log WARNING. |
| Markdown log write fails | Log to console only. Create log file on next success. |
| `Needs_Action/` write fails (escalation note) | Log escalation to Dashboard.md only. |
| Dashboard.md update fails | Skip update. Log ERROR. Continue. |

---

## Acceptance Criteria

- [ ] Every Gold skill action produces a JSON entry in `Logs/YYYY-MM-DD.json`
- [ ] JSON schema matches the defined structure for every entry
- [ ] Error entries include `level`, `recovery_action`, `retry_count`
- [ ] L1/L2 errors return correct recovery action to calling skill
- [ ] L3 escalations create `Needs_Action/` note and pause the skill (not the system)
- [ ] L4 escalations update `Dashboard.md` and halt the Ralph Wiggum Loop
- [ ] JSON log is append-only — never overwritten
- [ ] Markdown log continues to be written in parallel (Bronze format)

## Constraints

- MUST NOT be the only log — always write both JSON and Markdown
- MUST NOT delete or overwrite existing log entries
- MUST NOT suppress errors — every failure must be logged before recovery
- MUST NOT auto-resolve L3/L4 escalations without human confirmation
- JSON file must be valid JSON at all times (use append-safe write)

## Related Skills

- `skills/ralph-wiggum.md` — calls this skill after every loop step
- `skills/error-recovery.md` — this skill supersedes it for Gold tier (error-recovery.md remains for Silver reference)
- `skills/weekly-audit.md` — reads `Logs/YYYY-MM-DD.json` for error summary

## Log Requirement

```
- `HH:MM:SS` | **RECOVER** | `skill/social-poster` → `retry/1` | ✅ | level: L1 | action: retry after 30s
- `HH:MM:SS` | **ESCALATE** | `skill/social-poster` → `Needs_Action/escalation.md` | ❌ | level: L3 | reason: session expired
- `HH:MM:SS` | **ESCALATE** | `loop/ceo-briefing` → `Dashboard.md` | ❌ | level: L4 | reason: critical vault error
```
