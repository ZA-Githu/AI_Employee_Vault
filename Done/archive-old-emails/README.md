---
title: "README"
status: pending
priority: medium
created: 2026-02-26
due: 2026-02-26
source: inbox
received_at: "2026-02-26 13:43:11"
processed_by: filesystem_watcher
tags: [action, agent, inbox]
agent_assigned: claude
---

# AI Employee Vault
## Personal AI Employee Hackathon 2026 — Bronze Tier

> **Owner:** Ismat Zehra
> **Agent:** Claude (claude-sonnet-4-6)
> **Vault Path:** `AI_Employee_Vault/`
> **Current Tier:** Bronze

---

## What Is This?

This is your **Personal AI Employee** workspace. It is an Obsidian vault structured so that Claude can act as a digital employee — capturing tasks, organizing them, acting on them, archiving completed work, and logging every action it takes.

Think of it as a shared desk between you (the CEO) and Claude (your AI Employee).

---

## Vault Structure

```
AI_Employee_Vault/
│
├── README.md                  ← You are here
├── Bronze-Constitution.md     ← Rules & requirements (read this first)
├── Dashboard.md               ← Daily status overview
├── Company_Handbook.md        ← Operating rules & policies
│
├── Inbox/                     ← Drop new tasks/ideas here
├── Needs_Action/              ← Active work queue
├── Done/                      ← Completed & archived work
├── Logs/                      ← Agent audit trail (append-only)
│
└── .claude/
    └── skills/                ← Agent skill definitions
```

---

## Quick Start (5 Steps)

### Step 1 — Open in Obsidian
Open `AI_Employee_Vault/` as a vault in Obsidian. All files are standard Markdown and will render correctly.

### Step 2 — Read the Constitution
Open `Bronze-Constitution.md`. This is the governing document. It defines every folder rule, naming convention, and acceptance criterion.

### Step 3 — Open the Dashboard
Open `Dashboard.md` for a daily overview of system status, pending tasks, and recent activity.

### Step 4 — Start a Claude Code Session
Open a terminal in the vault directory and start Claude Code:
```bash
claude
```
Claude will read `Bronze-Constitution.md` and be ready to act as your AI Employee.

### Step 5 — Give Claude a Task
Type a command like:
```
triage inbox
```
or
```
new task — Write weekly report
```

---

## How the Workflow Works

```
You have something to do
        ↓
Drop a note in  Inbox/
        ↓
Tell Claude: "triage inbox"
        ↓
Claude moves it to  Needs_Action/  (if work needed)
                or  Done/          (if already resolved)
        ↓
Claude works on the task
        ↓
Tell Claude: "close task <filename>"
        ↓
Note moves to  Done/  with completion summary
        ↓
Log entry written to  Logs/YYYY-MM-DD.md
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `Bronze-Constitution.md` | Master rules — agent reads this every session |
| `Dashboard.md` | Your daily view — status, counts, activity |
| `Company_Handbook.md` | Communication style, priority keywords, policies |
| `README.md` | This file — setup and orientation |

---

## Commands Cheat Sheet

| Say This | Agent Does This |
|----------|----------------|
| `triage inbox` | Process all notes in Inbox/ |
| `new task — <title>` | Create note in Needs_Action/ |
| `close task <filename>` | Archive task to Done/ |
| `show status` | Refresh Dashboard |
| `what is pending?` | List Needs_Action items |
| `URGENT: <instruction>` | Treat as highest priority |

---

## Recommended Obsidian Plugins

These plugins enhance the vault but are not required for Bronze tier:

| Plugin | Why It Helps |
|--------|-------------|
| **Dataview** | Auto-count folder items on Dashboard |
| **Templater** | Auto-fill frontmatter when creating notes |
| **Calendar** | Visualize daily logs |
| **Tasks** | Render checkboxes as interactive task lists |

Install via: Obsidian Settings → Community Plugins → Browse

---

## Tier Roadmap

| Tier | Status | Unlocks |
|------|--------|---------|
| **Bronze** | 🔄 In Progress | Core workflow, folder structure, skills |
| **Silver** | 🔒 Locked | Recurring tasks, email/calendar integration |
| **Gold** | 🔒 Locked | Web research, report generation, APIs |
| **Platinum** | 🔒 Locked | Full autonomous loop, self-improvement |

Complete Bronze by satisfying all criteria in `Bronze-Constitution.md` Section 6.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Agent seems confused | Say: "re-read the constitution" |
| Task stuck in Inbox | Run `triage inbox` |
| Task stuck in Needs_Action | Say: `close task <filename>` with a resolution |
| Log not updating | Check `.claude/skills/log-action.md` exists |
| Skill not working | Verify file exists in `.claude/skills/` |

---

## Support & Feedback

This vault was built for the **Personal AI Employee Hackathon 2026**.
For issues or questions, provide Claude with the full error from `Logs/` and describe what you expected to happen.

---

*AI_Employee_Vault — Bronze Tier | Personal AI Employee Hackathon 2026*
