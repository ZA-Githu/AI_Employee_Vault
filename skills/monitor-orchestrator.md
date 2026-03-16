---
title: "Skill: Monitor Orchestrator"
id: skill-monitor-orchestrator
version: 1.0.0
tier: Gold — Social Manager Extension
tags: [skill, orchestrator, monitor, approved, social-manager, continuous, pm2]
---

# Skill: Monitor Orchestrator
**ID:** skill-monitor-orchestrator
**Version:** 1.0.0
**Tier:** Gold — Social Manager Extension
**Trigger:**
- `start orchestrator`
- `monitor approved folder`
- `run orchestrator once`
- `stop orchestrator`
- `orchestrator status`
- Auto-triggered: PM2 app `social-orchestrator` at system start

## Description

Continuously monitors `Approved/` for new approved social posts and
automatically calls `skills/executor-handler.md` (which runs
`watcher/master_orchestrator.py`) to publish them. Runs as a persistent
background process — either via PM2 or as a foreground terminal session.

The orchestrator is the automation layer between human approval and platform
execution. Once a human moves a file to `Approved/`, the orchestrator detects
it within the poll interval (default: 60 seconds) and triggers the executor
without any further human action.

All orchestrator activity is logged to `Logs/YYYY-MM-DD.json`. Failed posts
trigger a log entry and human notification — the orchestrator does not retry
automatically.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Start continuous monitor | `start orchestrator` | Poll Approved/ every 60s, execute as found |
| One-shot run | `run orchestrator once` | Process everything in Approved/ now, then exit |
| Dry-run | `dry-run orchestrator` | Show what would be posted, no browser |
| Stop orchestrator | `stop orchestrator` | Clean shutdown (if running in terminal) |
| Orchestrator status | `orchestrator status` | Show running state, last poll time, queue length |
| Set poll interval | `orchestrator interval <seconds>` | Change polling frequency |
| List queue | `show approved queue` | List all files in Approved/ with status and age |
| PM2 control | `pm2 start social-orchestrator` | Start as persistent PM2 background process |

---

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `interval` | integer | optional | Poll interval in seconds (default: 60, min: 30) |
| `once` | boolean | optional | Single pass then exit (default: false) |
| `dry_run` | boolean | optional | No browser, no execution — validate and log only |
| `platform` | string | optional | Only process files for this platform (default: all) |

---

## Outputs

### Per poll cycle
- Log entry: `ORCHESTRATOR_POLL` with queue count, timestamp, next poll time
- For each file processed: delegates to `executor-handler.md` which produces its own `SOCIAL_POST` log entry

### On new file detected
- Log entry: `ORCHESTRATOR_DISPATCH` — file name, platform, executor invoked
- Executor runs and produces success/failure output (see `executor-handler.md`)

### On orchestrator start
- Log entry: `ORCHESTRATOR_START` — interval, mode, timestamp
- Console banner printed

### On orchestrator stop (clean)
- Log entry: `ORCHESTRATOR_STOP` — posts processed this session, duration

### On failure detected (executor failed)
- Log entry: `ORCHESTRATOR_FAILURE` — filename, platform, screenshot path
- `Needs_Action/YYYY-MM-DD HH-MM — Orchestrator-Failure-<platform>.md` created if 3+ consecutive failures on same platform

---

## Terminal Commands (What This Skill Runs)

```bash
# Start continuous orchestrator (from vault root)
python watcher/master_orchestrator.py

# Custom interval (120 seconds)
python watcher/master_orchestrator.py --interval 120

# One-shot: process all current Approved/ files, then exit
python watcher/master_orchestrator.py --once

# Dry-run
python watcher/master_orchestrator.py --dry-run

# Platform filter
python watcher/master_orchestrator.py --platform twitter
```

All commands are run from the **vault root** directory.

---

## Approval Gate Enforcement

The orchestrator passes each file to the executor, which enforces the approval
gate. The orchestrator adds one pre-filter of its own before dispatching:

```
Pre-filter (orchestrator, before calling executor):
  ├─ file extension is .md                    → if not: skip silently
  ├─ frontmatter type == "social-post"        → if not: skip silently
  ├─ frontmatter approved_by is non-empty     → if not: skip + log SKIP
  ├─ frontmatter status == "approved"         → if not: skip (pending/failed/published)
  └─ frontmatter published is NOT set         → if set: skip (already done)
```

Files that pass pre-filter → dispatched to executor.
Files that fail pre-filter → silently skipped (or logged if `approved_by` is blank).

**The orchestrator never sets `approved_by`.** It only reads it.

---

## Processing Order

Within each poll cycle, approved files are processed in this order:

1. `priority: critical` — oldest first
2. `priority: high` — oldest first
3. `priority: medium` — oldest first
4. `priority: low` — oldest first
5. No priority set — oldest first (by file creation date)

Only one file is processed at a time. The orchestrator waits for the executor
to complete (success or failure) before picking up the next file. No parallel
posting.

---

## Scheduled Posts

If a file has `scheduled: YYYY-MM-DD HH:MM` in frontmatter, the orchestrator
skips it until the scheduled time is reached. Posts scheduled in the past are
executed immediately.

```yaml
scheduled: 2026-03-01 09:00    # not executed until 2026-03-01 at 09:00
scheduled:                      # blank = post immediately on next poll
```

---

## PM2 Integration

The orchestrator is designed to run persistently under PM2 alongside existing
Gold Tier watchers. Add this block to `watcher/ecosystem.config.js`:

```js
{
  name        : "social-orchestrator",
  script      : "master_orchestrator.py",
  interpreter : PYTHON,
  cwd         : CWD,
  args        : "--interval 60",
  autorestart : true,
  max_restarts: 10,
  restart_delay: 15000,
  watch       : false,
  out_file    : `${CWD}\\..\\Logs\\pm2-social-orchestrator-out.log`,
  error_file  : `${CWD}\\..\\Logs\\pm2-social-orchestrator-err.log`,
  log_date_format: "YYYY-MM-DD HH:mm:ss",
  env: {
    DRY_RUN  : "false",
    LOG_LEVEL: "INFO",
    ORCHESTRATOR_INTERVAL: "60",
  },
}
```

PM2 commands:
```bash
pm2 start ecosystem.config.js --only social-orchestrator
pm2 stop social-orchestrator
pm2 restart social-orchestrator
pm2 logs social-orchestrator
```

---

## Failure Handling

| Situation | Orchestrator Response |
|---|---|
| Executor success | Log ORCHESTRATOR_DISPATCH success, continue poll |
| Executor failure | Log ORCHESTRATOR_FAILURE, file stays in Approved/ with status: failed |
| 3 consecutive failures (same platform) | Create Needs_Action/ escalation note, pause that platform |
| Session expired | Executor reports L3 — orchestrator logs, skips platform, others continue |
| Approved/ folder missing | Log ERROR, create folder, continue |
| Malformed frontmatter | Skip file, log SKIP with filename |
| Executor process crash | Orchestrator catches exception, logs, continues to next file |

**Consecutive failure tracking:** The orchestrator tracks failure counts per
platform. After 3 failures on the same platform within one session, it creates
a `Needs_Action/` escalation note and pauses dispatching to that platform.
Other platforms continue unaffected. Counter resets when a post succeeds.

---

## Steps — Continuous Mode

1. **Log ORCHESTRATOR_START.** Print banner with interval, mode, vault path.
2. **Poll loop (every `interval` seconds):**
   a. Scan `Approved/` for `.md` files matching pre-filter conditions.
   b. If queue empty → log `ORCHESTRATOR_POLL` (queue: 0) → wait `interval` → repeat.
   c. If queue non-empty → sort by priority and creation date.
   d. For each file in sorted order:
      - Check scheduled time — skip if not yet reached.
      - Log `ORCHESTRATOR_DISPATCH`.
      - Call `executor-handler.md` (which runs `social_media_executor_v2.py`).
      - Wait for completion.
      - Log result (success or failure).
      - Update consecutive failure counter.
      - If 3 consecutive failures on same platform → escalate + pause platform.
      - Sleep 5 seconds between posts (rate limit protection).
3. **On Ctrl+C or `stop orchestrator`:** Log `ORCHESTRATOR_STOP` with session summary. Clean exit.

## Steps — One-Shot Mode

1. **Log ORCHESTRATOR_START** (mode: once).
2. Scan `Approved/` — collect all qualifying files.
3. Sort by priority and creation date.
4. Process each file in sequence (same as step 2d above).
5. Log `ORCHESTRATOR_STOP` after last file. Exit.

---

## Example Session

```
Human: "start orchestrator"

  ════════════════════════════════════════════════════
    AI Employee Vault — Social Media Orchestrator
    Gold Tier | Social Manager Extension
    Mode      : LIVE
    Interval  : 60s
    Vault     : AI_Employee_Vault/
    Watching  : Approved/
  ════════════════════════════════════════════════════

  [14:00:00] ORCHESTRATOR_START — interval: 60s
  [14:00:00] Poll #1 — scanning Approved/ ...
  [14:00:00]   Queue: 2 files found
  [14:00:00]   Dispatching: 2026-02-27 — Product Launch — facebook.md (priority: high)
  [14:00:00]   → executor: ✅ posted | url: https://facebook.com/posts/123
  [14:00:05]   Dispatching: 2026-02-27 — Launch Tweet — twitter.md (priority: medium)
  [14:00:05]   → executor: ✅ posted | url: https://x.com/status/456
  [14:01:05] Poll #2 — Queue: 0 files — waiting 60s ...
  [14:02:05] Poll #3 — Queue: 0 files — waiting 60s ...
  ^C
  [14:02:30] ORCHESTRATOR_STOP — posts: 2 | failures: 0 | duration: 2m 30s
```

---

## Acceptance Criteria

- [ ] Orchestrator only processes files with `approved_by` set and `status: approved`
- [ ] Files without `approved_by` are skipped — never dispatched
- [ ] Processing order follows priority then creation date
- [ ] Scheduled posts not dispatched before their scheduled time
- [ ] Failures logged with screenshot path from executor
- [ ] After 3 consecutive failures on a platform → escalation note created
- [ ] Other platforms continue when one platform has 3 failures
- [ ] PM2 config block documented and compatible with ecosystem.config.js
- [ ] One-shot mode exits cleanly after processing full queue
- [ ] Every poll cycle produces a log entry

## Constraints

- MUST NOT process files with blank `approved_by`
- MUST NOT post in parallel — one post at a time, wait for completion
- MUST NOT auto-retry failed posts — leave for human re-approval
- MUST NOT modify `Pending_Approval/` files — read Approved/ only
- MUST NOT set poll interval below 30 seconds (platform rate limit protection)
- MUST log every dispatch and its outcome

## Related Skills

- `skills/social-drafter.md` — creates the drafts upstream
- `skills/executor-handler.md` — called for each file dispatched by orchestrator
- `skills/approval-handler.md` — human approval step (between drafter and orchestrator)
- `skills/audit-logger.md` — JSON log writer for all orchestrator events
- `skills/error-recovery.md` — L1-L4 classification for escalation decisions
- `skills/ralph-wiggum.md` — multi-step loops may chain the orchestrator

## Log Requirement

```
- `HH:MM:SS` | **ORCHESTRATOR_START** | `skills/monitor-orchestrator` → `Approved/` | ✅ | interval: 60s | mode: continuous
- `HH:MM:SS` | **ORCHESTRATOR_POLL** | `Approved/` → — | ✅ | queue: 2 | next_poll: HH:MM:SS
- `HH:MM:SS` | **ORCHESTRATOR_DISPATCH** | `Approved/file.md` → `executor-handler` | ✅ | platform: facebook
- `HH:MM:SS` | **ORCHESTRATOR_FAILURE** | `Approved/file.md` → — | ❌ | platform: instagram | screenshot: Logs/screenshots/...png
- `HH:MM:SS` | **ORCHESTRATOR_STOP** | `skills/monitor-orchestrator` → — | ✅ | posts: 5 | failures: 1 | duration: 12m 04s
```
