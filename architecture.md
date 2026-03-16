---
title: "AI Employee Vault — System Architecture"
type: architecture
tier: Bronze + Silver + Gold
created: 2026-02-27
tags: [architecture, system, gold]
---

# AI Employee Vault — System Architecture

> **Owner:** Ismat Zehra  |  **Agent:** Claude  |  **Built:** Hackathon 2026

---

## Full System ASCII Diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                        AI EMPLOYEE VAULT                                     ║
║                   Personal AI Employee — Gold Tier                           ║
╚══════════════════════════════════════════════════════════════════════════════╝

  INPUTS                  AGENT LAYER                    OUTPUTS
  ──────                  ───────────                    ───────

  📧 Gmail          ──►  gmail_watcher.py          ──►  Inbox/ notes
  💬 WhatsApp       ──►  whatsapp_watcher.py        ──►  Inbox/ notes
  🔗 LinkedIn DMs   ──►  linkedin_watcher.py        ──►  Inbox/ notes
  📁 File drop      ──►  filesystem_watcher.py      ──►  Needs_Action/ triage
  📘 Facebook DMs   ──►  facebook_watcher.py        ──►  Inbox/ notes
  📸 Instagram DMs  ──►  instagram_watcher.py       ──►  Inbox/ notes
  🐦 Twitter DMs    ──►  twitter_watcher.py         ──►  Inbox/ notes

                               │
                               ▼
                    ╔══════════════════╗
                    ║   VAULT CORE     ║
                    ║                  ║
                    ║  Inbox/          ║
                    ║  Needs_Action/   ║
                    ║  Plans/          ║
                    ║  Done/YYYY-MM/   ║
                    ║  Logs/           ║
                    ╚══════════════════╝
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
        APPROVAL GATE    RALPH LOOP       AUDIT ENGINE
        ─────────────    ──────────       ────────────
        Pending_         ralph_loop.py    audit_logger.py
        Approval/  ──►   (stop-hook)      JSON + MD logs
               │         ↕ state          L1-L4 recovery
               │         Plans/
               ▼
        Approved/  ──►  SOCIAL POSTERS ──►  PLATFORMS
        Rejected/        │
                         ├── facebook_poster.py  ──►  Facebook
                         ├── instagram_poster.py ──►  Instagram
                         ├── twitter_poster.py   ──►  Twitter/X
                         └── linkedin_poster.py  ──►  LinkedIn

                               │
                               ▼
                    ╔══════════════════╗
                    ║  WEEKLY AUDIT    ║
                    ║                  ║
                    ║  weekly_audit.py ║
                    ║  Accounting/ ──► ║
                    ║  Briefings/ ──►  ║
                    ║  Dashboard.md ◄──║
                    ╚══════════════════╝ 
```

---

## Layer-by-Layer Breakdown

### Bronze Tier — Foundation

| Component | Script | Purpose |
|-----------|--------|---------|
| Base class | `base_watcher.py` | Shared config, logging, vault log writer |
| File watcher | `filesystem_watcher.py` | Watchdog on Inbox/, routes to Needs_Action/ |
| Vault log | `Logs/YYYY-MM-DD.md` | Markdown append-only audit trail |

**Vault folders:**
```
Inbox/          ← All incoming notes land here
Needs_Action/   ← Active tasks queue
Done/YYYY-MM/   ← Archive, month-partitioned
Logs/           ← Append-only log files
```

---

### Silver Tier — Integrations + Approval

| Component | Script | Purpose |
|-----------|--------|---------|
| Gmail | `gmail_watcher.py` | Gmail API poller, writes Inbox/ notes |
| WhatsApp | `whatsapp_watcher.py` | Playwright DM monitor |
| LinkedIn watch | `linkedin_watcher.py` | LinkedIn DM/notification watcher |
| LinkedIn post | `linkedin_poster.py` | Playwright poster with approval gate |
| Email MCP | `email_mcp.py` | Gmail MCP server for Claude |

**Approval pipeline:**
```
Plans/  →  Pending_Approval/  →  (human reviews)  →  Approved/ or Rejected/
```

**SLA:** Plans in `Pending_Approval/` older than 48 hours trigger an escalation note.

---

### Gold Tier — Autonomy + Multi-Platform

| Component | Script | Purpose |
|-----------|--------|---------|
| Audit Logger | `audit_logger.py` | JSON + MD dual-log, L1-L4 recovery |
| Facebook Poster | `facebook_poster.py` | Playwright, approval gate required |
| Instagram Poster | `instagram_poster.py` | Playwright, approval gate, image support |
| Twitter Poster | `twitter_poster.py` | Playwright, 280-char limit enforced |
| Weekly Audit | `weekly_audit.py` | 7-section CEO Briefing, no external APIs |
| Ralph Loop | `ralph_loop.py` | Autonomous multi-step plan executor |

**Gold vault folders:**
```
Accounting/       ← Financial records, parsed by weekly_audit.py
Briefings/        ← CEO Briefings (YYYY-WW — CEO-Briefing.md)
Social_Summaries/ ← Weekly social post counts by platform
```

---

## Error Recovery — L1-L4 Classification

```
Exception
    │
    ▼
_classify_error()
    │
    ├── L1 Transient (network, rate-limit)
    │       → retry after 30s (max 3 attempts)
    │       → escalate to L3 if exhausted
    │
    ├── L2 Recoverable (file/format)
    │       → auto-fix frontmatter / path
    │       → retry once
    │
    ├── L3 Escalatable (auth, session, 401/403)
    │       → create Needs_Action/ escalation note
    │       → pause this skill
    │       → other skills continue
    │
    └── L4 Critical (vault corrupt, disk full)
            → create Needs_Action/ escalation note
            → update Dashboard.md with ⚠️ alert
            → halt Ralph Loop immediately
```

---

## Ralph Wiggum Loop — Execution Flow

```
Approved/<plan>.md
       │
       ▼
  _load_plan()  ──  validate approved_by + status == "approved"
       │
       ▼
  parse_steps()  ──  numbered list from ## Proposed Actions
       │
   ┌───┴───────────────────────┐
   │  For each step:           │
   │                           │
   │  1. STOP-HOOK check       │◄── plan recalled? Ctrl+C? timeout? failures?
   │     (before every step)   │
   │         │                 │
   │         ▼                 │
   │  2. identify_skill()      │◄── tweet? facebook? email? audit? manual?
   │         │                 │
   │         ▼                 │
   │  3. _execute_step()       │──► dispatched / manual note created
   │         │                 │
   │         ▼                 │
   │  4. _write_state()        │──► Plans/loop-state-<plan>.md (resumable)
   │         │                 │
   └─────────┘                 │
       │                       │
       ▼                       │
  All steps done?              │
       │ YES                   │
       ▼                       │
  _complete_loop()  ──►  Done/YYYY-MM/<plan>.md
                    ──►  delete state file
                    ──►  audit.log_action(LOOP_COMPLETE)
```

---

## MCP Server Configuration (`mcp.json`)

```json
{
  "mcpServers": {
    "email":   { "command": "python", "args": ["watcher/email_mcp.py"] },
    "social":  { "command": "python", "args": ["watcher/facebook_poster.py", "--mcp"] },
    "audit":   { "command": "python", "args": ["watcher/audit_logger.py",   "--mcp"] },
    "ralph":   { "command": "python", "args": ["watcher/ralph_loop.py",     "--mcp"] }
  }
}
```

---

## PM2 Process Map (`watcher/ecosystem.config.js`)

| PM2 App Name | Script | Mode |
|---|---|---|
| `filesystem-watcher` | filesystem_watcher.py | continuous |
| `gmail-watcher` | gmail_watcher.py | continuous, 5-min poll |
| `whatsapp-watcher` | whatsapp_watcher.py | continuous, 1-min poll |
| `linkedin-watcher` | linkedin_watcher.py | continuous, 5-min poll |
| `linkedin-poster` | linkedin_poster.py --watch | continuous |
| `facebook-watcher` | facebook_watcher.py | continuous, 5-min poll |
| `instagram-watcher` | instagram_watcher.py | continuous, 5-min poll |
| `twitter-watcher` | twitter_watcher.py | continuous, 5-min poll |
| `facebook-poster` | facebook_poster.py --watch | continuous |
| `instagram-poster` | instagram_poster.py --watch | continuous |
| `twitter-poster` | twitter_poster.py --watch | continuous |

---

## Session Isolation

Each Playwright script maintains its own browser session directory to prevent profile lock conflicts:

```
watcher/sessions/
    whatsapp/          ← whatsapp_watcher.py
    linkedin/          ← linkedin_poster.py
    linkedin-watcher/  ← linkedin_watcher.py  (separate to avoid lock)
    facebook/          ← facebook_poster.py + facebook_watcher.py
    instagram/         ← instagram_poster.py + instagram_watcher.py
    twitter/           ← twitter_poster.py + twitter_watcher.py
```

---

## Skill Definitions (`skills/`)

| Skill File | Tier | Maps to Script |
|---|---|---|
| `file-processing.md` | Bronze | filesystem_watcher.py |
| `vault-management.md` | Bronze | base_watcher.py |
| `watcher-management.md` | Bronze | filesystem_watcher.py |
| `gmail-watcher.md` | Silver | gmail_watcher.py |
| `whatsapp-watcher.md` | Silver | whatsapp_watcher.py |
| `linkedin-poster.md` | Silver | linkedin_poster.py |
| `approval-handler.md` | Silver | approval pipeline |
| `check-approvals.md` | Silver | Pending_Approval/ scan |
| `create-plan.md` | Silver | Plans/ creation |
| `social-poster.md` | Gold | facebook/instagram/twitter_poster.py |
| `weekly-audit.md` | Gold | weekly_audit.py |
| `ralph-wiggum.md` | Gold | ralph_loop.py |
| `audit-logger.md` | Gold | audit_logger.py |
| `cross-domain-integrator.md` | Gold | ralph_loop.py routing |
| `error-recovery.md` | Gold | audit_logger.py L1-L4 |

---

## Data Flow — Social Post (end-to-end)

```
Human idea
    │
    ▼ (Claude drafts)
Plans/2026-02-27 — Facebook-Product-Launch.md
    │ type: facebook-post
    │ status: draft
    │
    ▼ (submit-for-approval skill)
Pending_Approval/2026-02-27 — Facebook-Product-Launch.md
    │ status: pending
    │
    ▼ (human edits frontmatter)
Approved/2026-02-27 — Facebook-Product-Launch.md
    │ approved_by: human
    │ status: approved
    │
    ▼ (facebook_poster.py --watch detects file)
Browser opens → Facebook.com → post composed → Post clicked
    │
    ▼
Done/2026-02/2026-02-27 — Facebook-Product-Launch.md
    │ status: published
    │ post_url: https://facebook.com/posts/...
    │
    ▼
Logs/2026-02-27.json  ←  audit entry: SOCIAL_POST success
Logs/2026-02-27.md    ←  markdown entry (Bronze-compatible)
```

---

## Data Flow — Weekly Audit

```
Every Monday (or: python watcher/weekly_audit.py)
    │
    ├── scan Done/YYYY-MM/ for completed tasks this week
    ├── scan Needs_Action/ for open + blocked tasks
    ├── scan Logs/ for SOCIAL_POST entries by platform
    ├── scan Accounting/ for income/expense records
    ├── scan Pending_Approval/ for age > 48h flags
    └── scan Logs/ for ERROR/ESCALATE/LOOP_ABORT entries
    │
    ▼
Accounting/YYYY-WW — Accounting-Audit.md   ← financial table
Briefings/YYYY-WW — CEO-Briefing.md        ← 7-section executive briefing
Dashboard.md updated                        ← [[Briefings/...]] link prepended
Logs/YYYY-MM-DD.json                       ← BRIEFING_GEN + AUDIT_RUN entries
```

---

*Architecture — AI_Employee_Vault Gold Tier | Personal AI Employee Hackathon 2026*
