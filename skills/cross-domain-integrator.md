---
title: "Skill: Cross-Domain Integrator"
id: skill-cross-domain-integrator
version: 1.0.0
tier: Gold
tags: [skill, cross-domain, personal, business, routing, priority, gold]
---

# Skill: Cross-Domain Integrator
**ID:** skill-cross-domain-integrator
**Version:** 1.0.0
**Tier:** Gold
**Trigger:**
- Auto — runs at session start to classify and route items in `Inbox/` and `Needs_Action/`
- Manual: `classify tasks` | `route inbox` | `show domain queue`
- `prioritize tasks` | `cross-domain summary`

## Description

The Cross-Domain Integrator classifies all active vault items (in `Inbox/`, `Needs_Action/`, and incoming watcher routes) as **personal** or **business**, assigns priority within each domain, and routes them to the correct handling skill or queue. It bridges the Silver-tier email/WhatsApp watchers with the Gold-tier social/audit capabilities — ensuring that a single vault handles both the CEO's business workflow and their personal communication without conflict.

This skill runs first in every session and produces a prioritised cross-domain queue that the Ralph Wiggum Loop and other skills consume.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Classify inbox | `route inbox` | Tag all `Inbox/` items as personal/business |
| Classify tasks | `classify tasks` | Tag all `Needs_Action/` items as personal/business |
| Priority queue | `prioritize tasks` | Return ranked task list across both domains |
| Domain summary | `cross-domain summary` | Show counts per domain and skill assignment |
| Tag single item | `classify <filename>` | Classify one specific file |
| Domain filter | `show personal tasks` | List only personal domain items |
| Domain filter | `show business tasks` | List only business domain items |

---

## Domain Definitions

### Personal Domain
Items related to Ismat Zehra's personal life, education, communication, or private accounts.

| Source | Examples | Tags Added |
|--------|---------|-----------|
| Gmail (personal senders) | Family emails, bank OTPs, course notifications | `#personal`, `#email` |
| WhatsApp messages | Personal contacts, family, friends | `#personal`, `#whatsapp` |
| LinkedIn DMs | Recruiters, personal network | `#personal`, `#linkedin` |
| Tasks without org context | Personal errands, study, health | `#personal` |

### Business Domain
Items related to work, clients, social media management, or commercial activities.

| Source | Examples | Tags Added |
|--------|---------|-----------|
| Gmail (business senders) | Client emails, invoices, job applications | `#business`, `#email` |
| Social media mentions | Twitter mentions, Facebook page messages | `#business`, `#social` |
| LinkedIn (professional) | Job offers, work projects, B2B | `#business`, `#linkedin` |
| Accounting items | Invoices, expenses, financial records | `#business`, `#accounting` |
| Social post plans | `Plans/` items with type linkedin/twitter/facebook | `#business`, `#social` |

### Mixed Domain
Items that span both — e.g., a personal LinkedIn message from a client. Tagged `#mixed`. Routed as **business** by default unless human overrides.

---

## Classification Rules

The integrator reads each file's frontmatter and body and applies these rules in order:

| Priority | Rule | Domain |
|----------|------|--------|
| 1 | `domain:` field already set in frontmatter | Honour existing tag |
| 2 | `type: linkedin-post / twitter-post / facebook-post / instagram-post` | Business |
| 3 | `type: accounting-report` | Business |
| 4 | `type: ceo-briefing` | Business |
| 5 | `type: email` AND sender matches PERSONAL_SENDERS env list | Personal |
| 6 | `type: email` AND sender matches BUSINESS_SENDERS env list | Business |
| 7 | `type: whatsapp-message` AND contact in PERSONAL_CONTACTS | Personal |
| 8 | Keywords in title/body: `invoice, client, project, revenue, business` | Business |
| 9 | Keywords in title/body: `family, personal, study, health, course` | Personal |
| 10 | Default if no rule matches | Business (safer default) |

---

## Priority Scoring

After domain classification, items are scored 1–10 (higher = more urgent):

| Factor | Score Boost |
|--------|-------------|
| `priority: critical` in frontmatter | +4 |
| `priority: high` in frontmatter | +3 |
| `due:` date is today or overdue | +3 |
| `due:` date is within 2 days | +2 |
| `status: blocked` | +2 |
| Escalation note (`type: escalation`) | +4 |
| Plan waiting > 48h in `Pending_Approval/` | +3 |
| `priority: medium` in frontmatter | +1 |
| No due date | +0 |
| `priority: low` | −1 |

Output: a ranked list of items per domain, sorted by total score descending.

---

## Routing Map

After classification and scoring, items are routed to the correct skill:

| Domain | Type | Routed To |
|--------|------|-----------|
| Personal | Email | `skills/gmail-watcher.md` |
| Personal | WhatsApp | `skills/whatsapp-watcher.md` |
| Personal | LinkedIn DM | `skills/linkedin-poster.md` (watch mode) |
| Business | Social post | `skills/social-poster.md` |
| Business | LinkedIn post | `skills/linkedin-poster.md` |
| Business | Accounting | `skills/weekly-audit.md` |
| Business | Escalation | `skills/audit-logger.md` |
| Any | Multi-step plan | `skills/ralph-wiggum.md` |

---

## Inputs

- `scope` (string, optional): `inbox | needs_action | all` (default: `all`)
- `domain` (string, optional): `personal | business | all` filter (default: `all`)
- `dry_run` (boolean, optional): Classify and score without writing frontmatter changes

---

## Outputs

- Each classified file updated with `domain: personal | business | mixed` in frontmatter
- Priority score added as `domain_priority: N` in frontmatter
- A cross-domain queue summary (in-memory, reported to session)
- Log entry: `SKILL_RUN` with counts per domain

---

## Steps

1. **Scan scope.** Read all files in `Inbox/` and/or `Needs_Action/` based on `scope` input.
2. **For each file:**
   a. Check if `domain:` is already set — if so, skip classification (honour existing).
   b. Apply classification rules (table above) in order. First match wins.
   c. Calculate priority score (table above).
   d. Update file frontmatter with `domain:` and `domain_priority:`.
   e. Log `EDIT` for each file updated.
3. **Build queue.** Sort all items by domain_priority descending within each domain.
4. **Output summary.** Report counts:
   ```
   Personal: N items (top: <title>, priority: N)
   Business: N items (top: <title>, priority: N)
   Mixed:    N items
   ```
5. **Route.** For items with clear next skill, add `assigned_skill:` to frontmatter.
6. **Log SKILL_RUN.**

---

## Example — Classified File Frontmatter

```yaml
---
title: "Twitter mention from @client"
type: twitter-message
status: pending
priority: high
domain: business               # ← added by cross-domain-integrator
domain_priority: 8             # ← score: high(+3) + today's due(+3) + social(+2)
assigned_skill: social-poster  # ← routing decision
created: 2026-02-25
due: 2026-02-25
agent_assigned: claude
tags: [twitter, business, social, needs-action]
---
```

---

## Acceptance Criteria

- [ ] Every item in `Inbox/` and `Needs_Action/` gets a `domain:` tag after running
- [ ] Priority scoring matches the defined rules
- [ ] Items with existing `domain:` are not reclassified
- [ ] `assigned_skill:` set for items with clear routing
- [ ] Dry-run mode classifies without writing frontmatter
- [ ] Cross-domain summary reported at session start
- [ ] All frontmatter updates logged with `EDIT`

## Constraints

- MUST NOT reclassify items that already have `domain:` set
- MUST NOT move files — classification only, routing is informational
- MUST NOT expose personal domain data in business-domain reports
- MUST default to `business` when domain is ambiguous (`#mixed`)
- MUST update frontmatter in-place without altering the note body

## Environment Variables

```
PERSONAL_SENDERS=family@email.com,personal@email.com
BUSINESS_SENDERS=client@company.com,hr@company.com
PERSONAL_CONTACTS=Mom,Dad,Friend1
BUSINESS_KEYWORDS=invoice,client,project,revenue,deadline,meeting,proposal
PERSONAL_KEYWORDS=family,personal,study,health,course,home
```

## Related Skills

- `skills/ralph-wiggum.md` — consumes the domain queue for cross-domain loop execution
- `skills/weekly-audit.md` — uses `domain:` tags to split personal vs business in briefings
- `skills/audit-logger.md` — logs all classification events
- `skills/social-poster.md` — receives `#business` social items
- `skills/gmail-watcher.md` — receives `#personal` and `#business` email items

## Log Requirement

```
- `HH:MM:SS` | **SKILL_RUN** | `Inbox/` → `Needs_Action/` | ✅ | classified: 12 | personal: 4 | business: 7 | mixed: 1
- `HH:MM:SS` | **EDIT** | `Needs_Action/2026-02-25 — Twitter-mention.md` → — | ✅ | domain: business | priority: 8
```
