---
title: "Skill: Gmail Watcher"
id: skill-gmail-watcher
version: 1.0.0
tier: Silver
tags: [skill, gmail, email, watcher, silver]
---

# Skill: Gmail Watcher
**ID:** skill-gmail-watcher
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Auto — runs at session start. Manual — user says "check email" or "watch gmail"

## Description

Monitors a connected Gmail inbox for new emails. When new messages arrive, the agent reads the sender, subject, and body, then routes each email into the vault workflow: urgent or action-required emails become notes in `Needs_Action/`, informational emails are dropped into `Inbox/` for triage, and newsletters or notifications are logged and discarded. All actions pass through the standard Bronze triage pipeline.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Check inbox | `check email` | Fetch all unread emails since last check |
| Watch continuously | `watch gmail` | Poll Gmail at set interval during session |
| Process single email | `process email <id>` | Route one specific email into the vault |
| Show email queue | `email queue` | List emails waiting to be processed |
| Stop watcher | `stop gmail watcher` | Stop polling and report session summary |

## Inputs

- `mode` (string, optional, default `check`): One of `check | watch | process | queue | stop`
- `email_id` (string, required for process mode): Gmail message ID
- `interval` (integer, optional, default 300): Poll interval in seconds for watch mode (min 60)
- `filters` (list, optional): Sender addresses or subject keywords to prioritise

## Outputs

- Emails routed to `Inbox/` or `Needs_Action/` as `.md` notes
- Each note contains: sender, subject, date, body excerpt, and original email reference
- One log entry per email processed
- Session summary on stop

## Steps

1. **Check credentials.** Verify Gmail OAuth token is configured. If not, alert human and abort.
2. **Fetch unread emails** since the last recorded check timestamp (stored in `Logs/`).
3. **For each email:**
   a. Parse sender, subject, date, and body.
   b. **Classify intent:**
      - Contains action words or direct questions → `Needs_Action/`
      - Informational, FYI, or CC → `Inbox/`
      - Newsletter, notification, or promotion → log and skip (no vault note)
   c. **Build vault note** with frontmatter:
      ```yaml
      ---
      title: "<subject>"
      type: email
      status: pending
      from: "<sender>"
      received: YYYY-MM-DD HH:MM
      email_id: "<gmail_id>"
      tags: [email, inbox, agent]
      ---
      ```
   d. Write note to `Inbox/` or `Needs_Action/` using vault-management skill.
   e. Log action type `CREATE`.
4. **Update last-check timestamp** in today's log.
5. **Report summary:** X routed to Needs_Action, Y dropped to Inbox, Z skipped.

## Acceptance Criteria

- [ ] Only runs when Gmail credentials are configured
- [ ] Every processed email produces a vault note with complete frontmatter
- [ ] Newsletters and notifications are skipped, not silently ignored — logged
- [ ] Last-check timestamp is updated after every run
- [ ] No email is processed twice (duplicate check on email_id)
- [ ] One log entry per email processed

## Constraints

- MUST NOT read or store full email body if it contains sensitive data — excerpt only (first 500 chars)
- MUST NOT send, reply to, or delete emails — read-only access
- MUST NOT run without valid OAuth credentials
- MUST NOT poll faster than every 60 seconds
- MUST NOT create vault notes for newsletters, automated notifications, or spam

## Error Cases

| Error | Response |
|-------|----------|
| No credentials configured | Alert human with setup instructions, abort |
| OAuth token expired | Alert human to re-authenticate, abort |
| Gmail API rate limit hit | Wait and retry once; if fails again, log ERROR and stop |
| Email body unreadable | Create note with subject only, flag as `needs-review` |

## Log Requirement

**Per email processed:**
```
- `HH:MM:SS` | **CREATE** | `gmail:<email_id>` → `Inbox/<note>.md` | ✅ success | from: <sender> subject: <subject>
```
**Session summary:**
```
- `HH:MM:SS` | **SKILL_RUN** | `.claude/skills/gmail-watcher.md` | checked gmail: routed=N skipped=N errors=N | ✅ success
```
