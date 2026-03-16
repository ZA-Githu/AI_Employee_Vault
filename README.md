# AI Employee Vault

> A fully autonomous personal AI employee system — Bronze, Silver, and Gold tier — built for the Personal AI Employee Hackathon 2026.

**Owner:** Ismat Zehra
**Agent:** Claude (claude-sonnet-4-6)
**Status:** Gold Tier — Complete

---

## What Is This?

The **AI Employee Vault** is an Obsidian-compatible workspace where Claude acts as a digital employee. It captures tasks, triages them, executes them autonomously, posts to social media, monitors emails and WhatsApp, manages accounting in Odoo, and logs every action it takes — all governed by a tiered constitution.

Think of it as a **shared desk between you (CEO) and Claude (AI Employee)**.

---

## Architecture Overview

```
Bronze Tier  →  Filesystem watching, task triage, vault structure
Silver Tier  →  Gmail monitoring, WhatsApp, LinkedIn, MCP servers
Gold Tier    →  Autonomous loop (Ralph), audit logging, Facebook,
                Instagram, Twitter, weekly CEO briefings, Odoo
```

---

## Vault Folder Structure

```
AI_Employee_Vault/
│
├── README.md                    ← You are here
├── Bronze-Constitution.md       ← Bronze rules (task triage, vault)
├── Silver-Constitution.md       ← Silver rules (email, social)
├── Gold-Constitution.md         ← Gold rules (autonomous loop, audit)
├── Social-Manager-Constitution.md
├── Company_Handbook.md          ← Operating policies
├── Dashboard.md                 ← Daily status overview
├── Plan-Template.md             ← Plan lifecycle template
├── architecture.md              ← System design doc
│
├── Inbox/                       ← Drop new tasks/ideas here
├── Needs_Action/                ← Active work queue
├── Pending_Approval/            ← Waiting for human approval
├── Approved/                    ← Human-approved, ready to execute
├── Done/YYYY-MM/                ← Completed & archived by month
├── Rejected/                    ← Rejected plans/posts
├── Logs/                        ← Append-only audit trail
├── Plans/                       ← Strategic plans
├── Briefings/                   ← Weekly CEO briefings
├── Social_Summaries/            ← Social media post history
├── Accounting/                  ← Odoo accounting records
│
├── skills/                      ← Claude skill definitions (Markdown)
│   ├── vault-management.md
│   ├── file-processing.md
│   ├── gmail-watcher.md
│   ├── whatsapp-watcher.md
│   ├── linkedin-poster.md
│   ├── social-poster.md
│   ├── social-drafter.md
│   ├── ralph-wiggum.md          ← Autonomous loop controller
│   ├── weekly-audit.md
│   ├── audit-logger.md
│   ├── odoo-accounting.md
│   └── ...
│
└── watcher/                     ← All Python automation scripts
    ├── requirements.txt
    ├── ecosystem.config.js      ← PM2 process manager config
    ├── base_watcher.py          ← Abstract base class
    ├── filesystem_watcher.py    ← Bronze: Inbox/ watchdog
    ├── gmail_watcher.py         ← Silver: Gmail API poller
    ├── whatsapp_watcher.py      ← Silver: WhatsApp Playwright
    ├── linkedin_watcher.py      ← Silver: LinkedIn monitor
    ├── linkedin_poster.py       ← Silver: LinkedIn post
    ├── email_mcp.py             ← Silver: Gmail MCP server
    ├── facebook_poster.py       ← Gold: Facebook Playwright
    ├── instagram_poster.py      ← Gold: Instagram Playwright
    ├── twitter_poster.py        ← Gold: Twitter/X Playwright
    ├── audit_logger.py          ← Gold: JSON audit + L1-L4 recovery
    ├── ralph_loop.py            ← Gold: Autonomous loop
    ├── weekly_audit.py          ← Gold: CEO Briefing generator
    ├── master_orchestrator.py   ← Gold: Central orchestrator
    └── sessions/                ← Browser session data (gitignored)
```

---

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| Python 3.11+ | All watcher scripts | [python.org](https://python.org) |
| Node.js 18+ | PM2 process manager | [nodejs.org](https://nodejs.org) |
| PM2 | Keep watchers alive | `npm install -g pm2` |
| Playwright | Browser automation | `pip install playwright && playwright install chromium` |
| Obsidian | Vault viewer (optional) | [obsidian.md](https://obsidian.md) |
| Docker | Odoo accounting (Gold) | [docker.com](https://docker.com) |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ZA-Githu/AI_Employee_Vault.git
cd AI_Employee_Vault
```

### 2. Install Python dependencies

```bash
cd watcher
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure environment variables

Create a `.env` file inside `watcher/`:

```env
# Gmail API (Silver Tier)
GMAIL_CREDENTIALS_FILE=../client_secret_xxx.json
GMAIL_TOKEN_FILE=token.json

# Vault path
VAULT_PATH=C:/path/to/AI_Employee_Vault

# Check intervals (seconds)
GMAIL_CHECK_INTERVAL=60
WHATSAPP_CHECK_INTERVAL=30
LINKEDIN_CHECK_INTERVAL=120
```

### 4. Set up Gmail API credentials (Silver Tier)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable Gmail API
3. Create OAuth 2.0 credentials → Download as `client_secret_xxx.json`
4. Place the file at the vault root
5. Run `gmail_watcher.py` once to complete OAuth flow and generate `token.json`

### 5. Start all watchers with PM2

```bash
cd watcher
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

Check status:
```bash
pm2 list
pm2 logs
```

---

## Odoo Setup (Gold Tier — Accounting)

Odoo runs in Docker on port `8069`.

```bash
# First time setup
docker run -d -e POSTGRES_USER=odoo -e POSTGRES_PASSWORD=odoo \
  -e POSTGRES_DB=postgres --name db postgres:15

docker run -d -p 8069:8069 --name odoo --link db:db \
  -t odoo:17

# After PC reboot
docker start db && docker start odoo
```

Access Odoo at: `http://localhost:8069`

---

## Using Claude as Your AI Employee

### Start a session

Open a terminal in the vault root:

```bash
claude
```

Claude reads the constitutions and is ready to act as your employee.

### Core commands

| Command | What Claude Does |
|---------|-----------------|
| `triage inbox` | Process all notes in `Inbox/` |
| `new task — <title>` | Create note in `Needs_Action/` |
| `close task <filename>` | Archive task to `Done/` |
| `show status` | Refresh `Dashboard.md` |
| `what is pending?` | List `Needs_Action/` items |
| `URGENT: <instruction>` | Highest priority treatment |

### Social media posting (Silver/Gold)

| Command | What Claude Does |
|---------|-----------------|
| `draft linkedin post about <topic>` | Draft post, save to `Pending_Approval/` |
| `check approvals` | Review `Pending_Approval/` queue |
| `approve <filename>` | Move to `Approved/`, queue for posting |
| `post approved` | Execute all approved social posts |

### Autonomous loop (Gold — Ralph)

```
start ralph loop
```

Ralph Wiggum (`ralph_loop.py`) runs autonomously:
1. Checks Inbox → triages
2. Checks Approved → posts
3. Monitors Gmail/WhatsApp → responds
4. Writes audit log entry
5. Stops before every step for human review (stop-hook)

### Weekly CEO Briefing (Gold)

```
generate weekly briefing
```

Produces a 7-section Markdown report in `Briefings/`:
1. Executive Summary
2. Tasks Completed
3. Tasks In Progress
4. Social Media Activity
5. Email/WhatsApp Activity
6. Accounting Summary
7. Recommendations

---

## Tier System

| Tier | Status | Capabilities |
|------|--------|-------------|
| **Bronze** | ✅ Complete | Vault structure, task triage, skills framework, filesystem watcher |
| **Silver** | ✅ Complete | Gmail API, WhatsApp, LinkedIn, email MCP server |
| **Gold** | ✅ Complete | Facebook, Instagram, Twitter, autonomous loop, audit logging, Odoo, CEO briefings |
| **Platinum** | 🔒 Future | Full self-improvement, multi-agent coordination |

---

## Audit & Error Recovery

Every action is logged to `Logs/` in append-only Markdown files (`YYYY-MM-DD.md`).

The Gold tier uses a 4-level recovery system:

| Level | Name | Action |
|-------|------|--------|
| L1 | Retry | Automatic retry with backoff |
| L2 | Auto-fix | Claude attempts self-correction |
| L3 | Pause Skill | Skill disabled, human notified |
| L4 | Halt Loop | Full stop, CEO briefing generated |

---

## Plan Lifecycle

```
Plans/  →  Pending_Approval/  →  Approved/  →  Done/YYYY-MM/
                                           ↘  Rejected/
```

Human approval is required before any plan is executed. Claude will never skip this gate.

---

## Security Notes

- `client_secret_*.json` and `token.json` are gitignored — never commit OAuth credentials
- `watcher/sessions/` browser session data is gitignored
- Human approval gate (`Pending_Approval/ → Approved/`) is enforced for all social posts and plans
- Audit log is append-only — no entry is ever modified or deleted

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Claude seems confused | Say: `re-read the constitution` |
| Task stuck in Inbox | Run `triage inbox` |
| Playwright login required | Run the relevant `*_debug.py` script |
| Gmail auth expired | Delete `watcher/token.json`, re-run gmail_watcher.py |
| PM2 watcher not starting | `pm2 logs <app-name>` to check errors |
| Odoo not accessible | `docker start db && docker start odoo` |

---

## Project Structure — Key Scripts

| Script | Tier | What It Does |
|--------|------|-------------|
| `filesystem_watcher.py` | Bronze | Watches `Inbox/` for new files, auto-triages |
| `gmail_watcher.py` | Silver | Polls Gmail, creates notes in `Inbox/` |
| `whatsapp_watcher.py` | Silver | Monitors WhatsApp Web via Playwright |
| `linkedin_poster.py` | Silver | Posts approved content to LinkedIn |
| `email_mcp.py` | Silver | MCP server exposing Gmail to Claude |
| `facebook_poster.py` | Gold | Posts approved content to Facebook |
| `instagram_poster.py` | Gold | Posts approved content to Instagram |
| `twitter_poster.py` | Gold | Posts approved content to Twitter/X |
| `audit_logger.py` | Gold | Structured JSON audit log + L1-L4 recovery |
| `ralph_loop.py` | Gold | Fully autonomous loop with human stop-hooks |
| `weekly_audit.py` | Gold | Generates 7-section CEO Briefing |
| `master_orchestrator.py` | Gold | Central coordination of all Gold scripts |

---

## Contributing

This is a hackathon project. To extend it:

1. Add a new skill definition in `skills/<skill-name>.md`
2. Add a new Python script in `watcher/<script-name>.py`
3. Import `AuditLogger` from `audit_logger.py` in every new Gold script
4. Register the new script in `watcher/ecosystem.config.js`
5. Document the skill commands in this README

---

*AI Employee Vault — Gold Tier | Personal AI Employee Hackathon 2026*
*Built with Claude Code + Anthropic API*
