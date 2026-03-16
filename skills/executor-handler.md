---
title: "Skill: Executor Handler"
id: skill-executor-handler
version: 1.0.0
tier: Gold — Social Manager Extension
tags: [skill, executor, social-manager, playwright, terminal, hitl]
---

# Skill: Executor Handler
**ID:** skill-executor-handler
**Version:** 1.0.0
**Tier:** Gold — Social Manager Extension
**Trigger:**
- `execute post <filename>`
- `post approved <filename>`
- `run executor for <platform>`
- `post all approved`
- `dry-run executor <filename>`

## Description

Handles terminal-based execution of `watcher/social_media_executor_v2.py` for
human-approved social posts and messages. The skill reads an approved file from
`Approved/`, validates the approval gate, constructs the correct terminal command,
and invokes the executor. On success, the post is published and archived to
`Done/YYYY-MM/`. On failure, a screenshot is saved to `Logs/screenshots/` and
the file stays in `Approved/` for retry.

This skill is the direct interface between Claude and `social_media_executor_v2.py`.
It never opens a browser itself — it delegates all browser automation to the executor
script, which uses persistent Playwright sessions from `session/<platform>/`.

Extends `skills/social-poster.md` (Gold Tier) to add WhatsApp and Gmail support,
and routes execution through `social_media_executor_v2.py` instead of the
platform-specific Gold Tier poster scripts.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Execute one post | `execute post <filename>` | Run executor for a single approved file |
| Execute by platform | `run executor for facebook` | Execute all approved posts for one platform |
| Execute all approved | `post all approved` | Process every file in Approved/ in sequence |
| Dry-run | `dry-run executor <filename>` | Validate file, print content — no browser |
| Check session | `check session <platform>` | Confirm session/ dir exists and is non-empty |
| Retry failed | `retry failed <filename>` | Re-queue a `status: failed` file for human re-approval |
| List approved | `list approved posts` | Show all files in Approved/ ready to execute |

---

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `filename` | string | required (single) | Filename in `Approved/` — include `.md` extension |
| `platform` | string | required (platform mode) | `facebook \| instagram \| linkedin \| twitter \| whatsapp \| gmail` |
| `dry_run` | boolean | optional | Validate and print — no Playwright, no post (default: false) |
| `all` | boolean | optional | Process all files in `Approved/` in order of priority then creation date |

---

## Outputs

### On success
- Post published on target platform
- File moved: `Approved/<filename>.md` → `Done/YYYY-MM/<filename>.md`
- File frontmatter updated: `status: published`, `published: YYYY-MM-DD`, `post_url: <url>`
- Log entry: `SOCIAL_POST` (outcome: success) in `Logs/YYYY-MM-DD.json` + `.md`
- Human confirmation printed: post URL (if captured) + archive path

### On failure
- File stays in `Approved/<filename>.md` (NOT moved — human must retry)
- File frontmatter updated: `status: failed`, `failed_at: YYYY-MM-DD HH:MM`
- Screenshot saved: `Logs/screenshots/YYYY-MM-DD-HH-MM-SS-<platform>-<slug>.png`
- Log entry: `SOCIAL_POST` (outcome: failed) with `screenshot` path in JSON log
- Human notification: error message + screenshot path + retry instruction

### On dry-run
- No browser opened, no file moved
- Post content printed to console with character count
- Log entry: `SKILL_RUN` (notes: dry-run)

---

## Approval Gate (Hard Requirement — Cannot Be Bypassed)

Before calling the executor, ALL of these conditions must be true or execution
is aborted:

```yaml
# The file in Approved/ must have ALL of these:
type: social-post           # must be exactly "social-post"
approved_by: human          # must be non-empty string — "human" preferred
status: approved            # must be "approved" (not "pending", "failed", "published")
platform: <valid>           # must be one of the 6 supported platforms
published:                  # must NOT already be set — prevents double-posting
```

If any condition fails:
- Log `ERROR` with the failing condition
- Do NOT open browser
- Do NOT call executor
- Tell human exactly which field is missing or wrong

---

## Terminal Commands (What This Skill Runs)

```bash
# Single file
python watcher/social_media_executor_v2.py --post "<filename>"

# Dry-run
python watcher/social_media_executor_v2.py --post "<filename>" --dry-run

# All files for one platform
python watcher/social_media_executor_v2.py --platform facebook

# All approved files across all platforms
python watcher/social_media_executor_v2.py --all

# Session check (non-posting)
python watcher/social_media_executor_v2.py --check-session <platform>
```

All commands are run from the **vault root** directory so relative paths resolve
correctly. The executor handles session management, Playwright launch, and
platform-specific posting logic internally.

---

## Session Management

Each platform uses a persistent Chromium profile stored in `session/<platform>/`.

| Platform | Session Path | First Run Behaviour |
|----------|-------------|---------------------|
| Facebook | `session/facebook/` | Opens browser, waits for manual login |
| Instagram | `session/instagram/` | Opens browser, waits for manual login |
| LinkedIn | `session/linkedin/` | Opens browser, waits for manual login |
| Twitter/X | `session/twitter/` | Opens browser, waits for manual login |
| WhatsApp | `session/whatsapp/` | Opens browser, scan QR code once |
| Gmail | `session/gmail/` | Opens browser, waits for manual login |

**Subsequent runs:** browser opens already logged in — no human action required.

**Session expired:** Executor detects login page → logs `L3 escalation` →
creates `Needs_Action/` note → stops that platform. Human re-authenticates by
running the executor once for that platform. Other platforms are unaffected.

---

## Steps

1. **Parse command.** Identify mode: single file, platform, all, dry-run, or session check.
2. **Validate approval gate.** Read frontmatter. Check all 5 gate conditions. Any failure → log `ERROR` → abort.
3. **Character limit check.** Re-validate post content length against platform limits. Over limit → abort.
4. **Dry-run branch.** If `dry_run: true` → print content + char count → log `SKILL_RUN` → stop.
5. **Check session directory.** Confirm `session/<platform>/` exists. If empty (first run) → inform human that a one-time login will be required.
6. **Build terminal command.** Construct the `social_media_executor_v2.py` command with correct args.
7. **Execute.** Run the command via terminal. Wait for completion.
8. **Handle result:**
   - **Success:** Confirm post URL. Verify file moved to `Done/YYYY-MM/`. Log `SOCIAL_POST` success.
   - **Failure:** Read screenshot path from executor output. Log `SOCIAL_POST` failure with screenshot path. Inform human.
9. **Confirmation.** Tell human: success (with post URL) or failure (with screenshot path and retry instruction).

---

## Failure Handling

| Failure Type | Executor Response | This Skill's Response |
|---|---|---|
| Session expired / logged out | L3 escalation in Needs_Action/ | Tell human to re-authenticate |
| Selector not found (UI changed) | Screenshot + error log | Show screenshot path, suggest retry after checking platform |
| Timeout (slow load) | Screenshot + error log | Suggest retry — likely transient |
| Content too long | Hard abort before browser | Tell human to shorten content |
| Missing `approved_by` | Abort before browser | Tell human exactly which field is missing |
| Double-post guard (published: set) | Skip + log | Inform human post already published |
| Network error | Screenshot + error log | Suggest retry — L1 transient |

**Retry rule:** Failed posts stay in `Approved/` with `status: failed`. To retry,
the human must reset `status: approved` in the file (removing `failed_at:`).
This prevents accidental double-posting.

---

## Example Session

```
Human: "execute post 2026-02-27 — Product Launch — facebook.md"

  [executor-handler] Reading Approved/2026-02-27 — Product Launch — facebook.md ...
  [executor-handler] Approval gate: ✅ type=social-post ✅ approved_by=human ✅ status=approved
  [executor-handler] Character count: 240 / 63,206 ✅
  [executor-handler] Session: session/facebook/ ✅ (already authenticated)
  [executor-handler] Running: python watcher/social_media_executor_v2.py --post "..."
  [executor-handler] Browser: opened Facebook, navigated to home feed ...
  [executor-handler] Posting: typed content, clicked Post button ...
  [executor-handler] ✅ Post published.
  [executor-handler] Post URL: https://facebook.com/posts/123456789
  [executor-handler] Archived: Done/2026-02/2026-02-27 — Product Launch — facebook.md
  [executor-handler] Log: SOCIAL_POST success → Logs/2026-02-27.json
```

```
Human: "dry-run executor 2026-02-27 — Launch Tweet — twitter.md"

  [executor-handler] Approval gate: ✅ all conditions met
  [executor-handler] [DRY-RUN] Would post (94 chars):
  [executor-handler] "Exciting news — our new feature is live! Try it today. #product #launch"
  [executor-handler] No browser opened. Log: SKILL_RUN dry-run.
```

---

## Acceptance Criteria

- [ ] Executor never called without all 5 approval gate conditions met
- [ ] `approved_by:` field checked — empty string or missing = abort
- [ ] Dry-run prints content and char count without browser
- [ ] On success: file moved to Done/, post_url recorded, log entry written
- [ ] On failure: file stays in Approved/, screenshot path logged, human informed
- [ ] Session directory checked before browser launch
- [ ] Retry instruction given on every failure
- [ ] Character limits re-validated before executor call

## Constraints

- MUST NOT post without `approved_by: human`
- MUST NOT move a `status: failed` file to Done/ automatically
- MUST NOT retry failed posts automatically — human must reset status
- MUST NOT share session directories between platforms
- MUST NOT modify post content before posting — publish exactly as written
- MUST leave file in `Approved/` on any failure

## Related Skills

- `skills/social-drafter.md` — creates the drafts that this skill executes
- `skills/monitor-orchestrator.md` — calls this skill automatically on new Approved/ files
- `skills/approval-handler.md` — the step between draft and execution
- `skills/social-poster.md` — Gold Tier poster (Facebook/Instagram/Twitter/LinkedIn)
- `skills/error-recovery.md` — L1-L4 classification for failures
- `skills/audit-logger.md` — JSON log writer

## Log Requirement

```
- `HH:MM:SS` | **SOCIAL_POST** | `Approved/2026-02-27 — Post — facebook.md` → `Done/2026-02/...` | ✅ success | platform: facebook | url: https://facebook.com/posts/123
- `HH:MM:SS` | **SOCIAL_POST** | `Approved/2026-02-27 — Post — instagram.md` → — | ❌ failed | platform: instagram | screenshot: Logs/screenshots/2026-02-27-10-15-00-instagram-post.png
- `HH:MM:SS` | **SKILL_RUN** | `skills/executor-handler` → — | ✅ success | dry-run | platform: twitter | chars: 94
```
