---
title: "Skill: Social Drafter"
id: skill-social-drafter
version: 1.0.0
tier: Gold — Social Manager Extension
tags: [skill, social, drafter, draft, pending-approval, social-manager]
---

# Skill: Social Drafter
**ID:** skill-social-drafter
**Version:** 1.0.0
**Tier:** Gold — Social Manager Extension
**Trigger:**
- `draft <platform> post about <topic>`
- `draft message to <contact> on <platform>`
- `create post for <platform>: <content>`
- `draft all platforms: <topic>`
- `batch draft <topic>` — generate one draft per platform simultaneously

## Description

Generates properly-formatted post/message draft `.md` files and saves them
directly to `Pending_Approval/` — ready for human review. Supports all six
platforms governed by `Social-Manager-Constitution.md`: Facebook, Instagram,
LinkedIn, Twitter/X, WhatsApp, and Gmail.

Each draft contains complete YAML frontmatter (platform, type, status, recipient
if required, image_path if required) and a `## Post Content` body section. The
draft is written — never posted. Posting only happens after explicit human approval
via `skills/executor-handler.md`.

Extends `skills/social-poster.md` (Gold Tier) by adding WhatsApp, Gmail, and
the Social Manager's `session/` layout and `type: social-post` contract.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Draft single post | `draft facebook post about <topic>` | One draft for one platform |
| Draft message | `draft whatsapp message to +44... about <topic>` | Message with recipient |
| Draft email | `draft gmail email to user@example.com re: <subject>` | Email with recipient + subject |
| Draft from file | `draft from content.md for instagram` | Use existing content file as body |
| Batch draft | `draft all platforms: <topic>` | One draft per platform, all six |
| List pending | `list pending drafts` | Show all files in Pending_Approval/ with age |
| Preview draft | `preview draft <filename>` | Show draft content without saving |

---

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `platform` | string | required | `facebook \| instagram \| linkedin \| twitter \| whatsapp \| gmail` |
| `topic` | string | required | Subject matter / talking points for the draft |
| `content` | string | optional | Verbatim post text — skips AI generation if provided |
| `recipient` | string | conditional | Required for `whatsapp` (phone/contact) and `gmail` (email address) |
| `subject` | string | conditional | Required for `gmail` only — email subject line |
| `image_path` | string | conditional | Required for `instagram`; optional for `facebook` |
| `priority` | string | optional | `low \| medium \| high \| critical` (default: `medium`) |
| `scheduled` | string | optional | `YYYY-MM-DD HH:MM` — executor checks this before posting |
| `allow_truncate` | boolean | optional | Twitter only — allow truncation to 280 chars (default: false) |

---

## Outputs

- One `.md` file per draft written to `Pending_Approval/`
- Filename format: `YYYY-MM-DD — <Title> — <platform>.md`
- File has complete YAML frontmatter + `## Post Content` section
- Log entry: `DRAFT_CREATE` written to `Logs/YYYY-MM-DD.json` and `Logs/YYYY-MM-DD.md`
- Human-readable confirmation printed: filename + character count + next step

---

## Draft File Format

Every file written to `Pending_Approval/` must follow this exact format:

```markdown
---
title: "<Post Title>"
platform: <platform>
type: social-post
status: pending
approved_by:
created: YYYY-MM-DD
priority: medium
scheduled:
image_path:
recipient:
subject:
allow_truncate: false
tags: [social, draft, <platform>]
---

## Post Content

<generated or provided post content>
```

**Field rules:**
- `approved_by` is always blank in the draft — only the human fills this
- `status` is always `pending` — changed to `approved` only by the human
- `type` is always `social-post` — executor uses this to distinguish from other plan types
- `image_path` and `recipient` left blank if not applicable to the platform
- `scheduled` left blank if posting immediately on approval

---

## Character Limits (Enforced Before Saving)

| Platform | Limit | Action if exceeded |
|----------|-------|-------------------|
| Twitter/X | 280 chars | Warn + show count — do not save unless human confirms or `allow_truncate: true` |
| Instagram | 2,200 chars | Hard reject — tell human to shorten |
| LinkedIn | 3,000 chars | Hard reject — tell human to shorten |
| Facebook | 63,206 chars | Hard reject |
| WhatsApp | 65,536 chars | Hard reject |
| Gmail | no hard limit | Warn if > 10,000 chars |

---

## Steps

1. **Parse intent.** Extract platform, topic/content, and optional fields (recipient, subject, image_path, priority) from the human's command.
2. **Validate platform.** Must be one of the six supported platforms. If unrecognised → inform human and abort.
3. **Validate required fields.** WhatsApp and Gmail require `recipient`. Gmail requires `subject`. Instagram should have `image_path` (warn if missing, do not hard-block).
4. **Generate or use content.** If verbatim content was provided, use it directly. Otherwise generate appropriate post text for the platform's style and character limit.
5. **Enforce character limits.** Count characters. If over limit → warn human with count, offer to trim if `allow_truncate: true`, otherwise abort.
6. **Build frontmatter.** Populate all fields. Leave `approved_by:` blank.
7. **Write file.** Save to `Pending_Approval/YYYY-MM-DD — <Title> — <platform>.md`.
8. **Log.** Write `DRAFT_CREATE` to `Logs/YYYY-MM-DD.json` and `Logs/YYYY-MM-DD.md`.
9. **Confirm.** Print filename, platform, character count, and next step: `"Review in Pending_Approval/ and say 'approve plan <filename>' when ready."`

---

## Approval Gate (Hard Requirement)

This skill **only creates drafts**. It never posts. `approved_by:` is always left
blank in the output file. Only the human can set `approved_by: human` and move the
file to `Approved/`. The executor will hard-reject any file without this field set.

```
DRAFT_CREATE  →  Pending_Approval/  (this skill)
                         ↓
              Human reviews and edits
                         ↓
              Human sets approved_by: human
              Human moves file to Approved/
                         ↓
              executor-handler or monitor-orchestrator publishes
```

---

## Example Commands and Outputs

### Example 1 — Facebook post
```
Human: "draft facebook post about our new product launch"

Output file: Pending_Approval/2026-02-27 — New Product Launch — facebook.md
---
title: "New Product Launch"
platform: facebook
type: social-post
status: pending
approved_by:
created: 2026-02-27
priority: medium
---

## Post Content

We're thrilled to announce our latest product launch! After months of hard work,
it's finally here. Visit our website to learn more and be among the first to try it.
```

### Example 2 — WhatsApp message with recipient
```
Human: "draft whatsapp message to +447700900123 about the meeting tomorrow"

Output file: Pending_Approval/2026-02-27 — Meeting Tomorrow — whatsapp.md
---
title: "Meeting Tomorrow"
platform: whatsapp
type: social-post
status: pending
approved_by:
recipient: "+447700900123"
created: 2026-02-27
---

## Post Content

Hi, just a reminder about our meeting tomorrow. Please let me know if you need
to reschedule. Looking forward to catching up!
```

### Example 3 — Twitter with character count warning
```
Human: "draft twitter post about the launch"

[Content generated: 94 chars — within 280 limit]
Output file: Pending_Approval/2026-02-27 — Launch — twitter.md
```

### Example 4 — Batch all platforms
```
Human: "draft all platforms: quarterly results are in — record growth"

Creates 6 files in Pending_Approval/:
  2026-02-27 — Quarterly Results — facebook.md
  2026-02-27 — Quarterly Results — instagram.md
  2026-02-27 — Quarterly Results — linkedin.md
  2026-02-27 — Quarterly Results — twitter.md
  2026-02-27 — Quarterly Results — whatsapp.md   ← warns: recipient required
  2026-02-27 — Quarterly Results — gmail.md       ← warns: recipient + subject required
```

---

## Acceptance Criteria

- [ ] Draft file always saved to `Pending_Approval/` — never to `Approved/` directly
- [ ] `approved_by:` always blank in every output file
- [ ] `type: social-post` present in every output file
- [ ] Character limit checked before saving — hard reject or warning per platform rules
- [ ] WhatsApp and Gmail drafts warn if `recipient` is missing (not hard-blocked)
- [ ] Instagram warns if `image_path` is missing
- [ ] Batch mode creates one file per platform
- [ ] Every draft creation logged with `DRAFT_CREATE`
- [ ] Human told the exact filename and next step after every draft

## Constraints

- MUST NOT set `approved_by` in any draft
- MUST NOT save directly to `Approved/` — always `Pending_Approval/`
- MUST NOT post or open any browser
- MUST NOT modify files in `Approved/`, `Done/`, or `Logs/`
- MUST warn (not hard-block) if Instagram `image_path` is missing
- MUST hard-block if Twitter content exceeds 280 chars and `allow_truncate` is false

## Related Skills

- `skills/social-poster.md` — Gold Tier posting skill (reused for Facebook/Instagram/Twitter)
- `skills/executor-handler.md` — executes approved social-posts via terminal
- `skills/monitor-orchestrator.md` — monitors Approved/ and triggers executor automatically
- `skills/approval-handler.md` — handles the human approval step between draft and execution

## Log Requirement

```
- `HH:MM:SS` | **DRAFT_CREATE** | `skills/social-drafter` → `Pending_Approval/2026-02-27 — Launch — facebook.md` | ✅ success | platform: facebook | chars: 240
- `HH:MM:SS` | **DRAFT_CREATE** | `skills/social-drafter` → `Pending_Approval/2026-02-27 — Launch — twitter.md` | ✅ success | platform: twitter | chars: 94
- `HH:MM:SS` | **DRAFT_CREATE** | `skills/social-drafter` → `Pending_Approval/2026-02-27 — Launch — whatsapp.md` | ⚠️ warning | platform: whatsapp | recipient: missing
```
