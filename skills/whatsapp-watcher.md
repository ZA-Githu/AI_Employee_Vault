---
title: "Skill: WhatsApp Watcher"
id: skill-whatsapp-watcher
version: 1.0.0
tier: Silver
tags: [skill, whatsapp, messaging, watcher, silver]
---

# Skill: WhatsApp Watcher
**ID:** skill-whatsapp-watcher
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Auto — runs at session start. Manual — user says "check whatsapp" or "watch whatsapp"

## Description

Monitors a connected WhatsApp account for new messages from specified contacts or groups. When messages arrive, the agent reads them, classifies their intent, and routes them into the vault. Task-oriented messages become `Needs_Action/` notes. Conversations or FYIs land in `Inbox/`. The agent never replies autonomously — all outbound messages require human approval via the standard approval workflow.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Check messages | `check whatsapp` | Fetch all unread messages since last check |
| Watch continuously | `watch whatsapp` | Poll WhatsApp at set interval during session |
| Process single chat | `process chat <contact>` | Route messages from one contact into vault |
| Show message queue | `whatsapp queue` | List unprocessed messages |
| Draft reply | `draft reply to <contact>` | Create a reply draft in Plans/ for approval |
| Stop watcher | `stop whatsapp watcher` | Stop polling and report session summary |

## Inputs

- `mode` (string, optional, default `check`): One of `check | watch | process | queue | draft-reply | stop`
- `contact` (string, required for process/draft-reply): Contact name or phone number
- `interval` (integer, optional, default 300): Poll interval in seconds (min 60)
- `watch_list` (list, optional): Contacts or groups to monitor (all contacts if empty)

## Outputs

- Messages routed to `Inbox/` or `Needs_Action/` as `.md` notes
- Reply drafts created in `Plans/` using Silver Plan Template
- One log entry per message batch processed
- Session summary on stop

## Steps

1. **Check credentials.** Verify WhatsApp Business API or WhatsApp Web connection is configured. If not, alert human and abort.
2. **Fetch unread messages** from all contacts (or watch_list if set) since last check.
3. **For each message batch (per contact):**
   a. Parse sender, timestamp, and message content.
   b. **Classify intent:**
      - Contains a question, request, or task → `Needs_Action/`
      - Update, FYI, or casual conversation → `Inbox/`
      - Group broadcast or notification → log and skip
   c. **Build vault note** with frontmatter:
      ```yaml
      ---
      title: "WhatsApp: <contact> — <date>"
      type: whatsapp-message
      status: pending
      from: "<contact>"
      received: YYYY-MM-DD HH:MM
      message_count: N
      tags: [whatsapp, inbox, agent]
      ---
      ```
   d. Include message content (up to 1000 chars) in note body.
   e. Write note using vault-management skill.
   f. Log action type `CREATE`.
4. **Draft reply flow (if requested):**
   a. Create plan in `Plans/` titled `Reply to <contact> — YYYY-MM-DD.md`
   b. Populate with: original message, proposed reply, tone, and rationale
   c. Submit to `Pending_Approval/` automatically (or prompt user)
5. **Update last-check timestamp** in today's log.
6. **Report summary:** X notes created, Y replies drafted, Z skipped.

## Acceptance Criteria

- [ ] Only runs when WhatsApp credentials are configured
- [ ] Every processed message batch produces a vault note with complete frontmatter
- [ ] Agent never sends a reply without an approved plan in `Approved/`
- [ ] Reply drafts use the Silver Plan Template
- [ ] Last-check timestamp updated after every run
- [ ] No message batch is processed twice

## Constraints

- MUST NOT send any WhatsApp message without an `Approved/` plan entry
- MUST NOT store full conversation history — last 5 messages per contact only
- MUST NOT process messages from contacts not in watch_list if watch_list is set
- MUST NOT run without valid API credentials
- MUST NOT poll faster than every 60 seconds
- MUST flag any message containing financial, legal, or medical content to the human immediately

## Error Cases

| Error | Response |
|-------|----------|
| No credentials configured | Alert human with setup instructions, abort |
| API connection failed | Retry once after 30 seconds; if fails, log ERROR and stop |
| Message content unreadable (media) | Create note with sender + timestamp + "[media message]" |
| Rate limit hit | Wait for reset window, log WARNING, continue when available |

## Log Requirement

**Per contact processed:**
```
- `HH:MM:SS` | **CREATE** | `whatsapp:<contact>` → `Inbox/<note>.md` | ✅ success | N messages from <contact>
```
**Session summary:**
```
- `HH:MM:SS` | **SKILL_RUN** | `.claude/skills/whatsapp-watcher.md` | checked whatsapp: notes=N drafts=N skipped=N | ✅ success
```
