---
title: "Skill: Watcher Management"
id: skill-watcher-management
version: 1.0.0
tier: Bronze
tags: [skill, watcher, automation, monitoring]
---

# Skill: Watcher Management
**ID:** skill-watcher-management
**Version:** 1.0.0
**Tier:** Bronze
**Trigger:** Manual — user says "start watcher", "stop watcher", or "watcher status"

## Description

Manages the Inbox watcher — a monitoring process that detects when new files are dropped into `Inbox/` and triggers the file-processing skill automatically. Provides start, stop, and status commands so the human always knows whether the vault is being actively monitored. At Bronze Tier, the watcher is session-scoped (active only while Claude is running).

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Start Watcher | `start watcher` | Begin monitoring Inbox/ for new files |
| Stop Watcher | `stop watcher` | Stop monitoring and report final summary |
| Watcher Status | `watcher status` | Report whether watcher is active and last check time |
| Manual Check | `check inbox` | One-time check of Inbox/ without starting the watcher |

## Inputs

- `operation` (string, required): One of `start | stop | status | check`
- `interval` (integer, optional, default 60): How often to check Inbox/ in seconds (Bronze: 60–300)
- `auto_process` (boolean, optional, default true): Whether to auto-trigger file-processing when new files are detected

## Outputs

- **start:** Confirmation message with watcher settings (interval, auto_process state)
- **stop:** Final summary — files detected and processed during the session
- **status:** Current state (active/inactive), last check time, files detected count
- **check:** Immediate Inbox/ file count and list

## States

| State | Meaning |
|-------|---------|
| `inactive` | Watcher is not running — Inbox/ is not being monitored |
| `active` | Watcher is running — checks Inbox/ on the set interval |
| `paused` | Watcher is temporarily paused — will resume automatically |
| `error` | Watcher encountered a problem — human attention required |

## Steps

### Start Watcher
1. Check if watcher is already active — if yes, report current state and stop.
2. Record start time and settings.
3. Set state to `active`.
4. Perform an immediate first check of `Inbox/`.
5. If `auto_process` is true and files are found, trigger file-processing skill.
6. Log action type `SKILL_RUN` with detail "watcher started".
7. Confirm to user: watcher is active, interval, auto_process setting.

### Stop Watcher
1. Check if watcher is active — if not, report "watcher is not running".
2. Set state to `inactive`.
3. Report session summary: duration active, total files detected, total files processed.
4. Log action type `SKILL_RUN` with detail "watcher stopped".

### Watcher Status
1. Read current watcher state.
2. Return: state, start time (if active), last check time, files detected this session.
3. No log entry required for status checks.

### Manual Check
1. List all files currently in `Inbox/`.
2. Return file count and names.
3. If `auto_process` is true, ask human: "Process these files now?"
4. Log action type `LIST`.

## Watcher Session Log

When the watcher is active, it writes a summary line to today's log at each interval:

```
- `HH:MM:SS` | **SKILL_RUN** | `watcher-management` | Inbox check: <N> files found | ✅ active
```

If new files are detected and processed:
```
- `HH:MM:SS` | **SKILL_RUN** | `watcher-management` → `file-processing` | <N> new files detected, processing triggered | ✅ success
```

## Acceptance Criteria

- [ ] Start command confirms watcher is active with correct settings
- [ ] Stop command reports a session summary before stopping
- [ ] Status command returns accurate current state
- [ ] Watcher does not run if already active (no duplicate watchers)
- [ ] Every start and stop event is logged
- [ ] Manual check returns accurate Inbox file list
- [ ] Watcher triggers file-processing when new files are detected (if auto_process true)

## Constraints

- MUST NOT start a second watcher if one is already running
- MUST NOT set interval below 60 seconds (Bronze tier minimum)
- MUST NOT auto-delete files — only detect and route to file-processing skill
- MUST NOT access folders outside of `Inbox/` during watch cycles
- MUST stop cleanly without leaving orphaned processes when session ends
- MUST report watcher state in every session status check

## Error Cases

| Error | Response |
|-------|----------|
| Watcher already running | Report current state, offer to restart |
| Inbox/ folder missing | Log `ERROR`, alert human, set state to `error` |
| File-processing skill unavailable | Detect files but queue them; alert human |
| Interval value out of range | Default to 60 seconds, warn human |

## Log Requirement

**On start:**
```
- `HH:MM:SS` | **SKILL_RUN** | `.claude/skills/watcher-management.md` | watcher started — interval: <N>s, auto_process: <true/false> | ✅ success
```

**On stop:**
```
- `HH:MM:SS` | **SKILL_RUN** | `.claude/skills/watcher-management.md` | watcher stopped — session: <duration>, detected: <N> files | ✅ success
```
