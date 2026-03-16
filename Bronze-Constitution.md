# Bronze-Constitution
## Personal AI Employee Hackathon 2026 — Bronze Tier

> **Tier:** Bronze (Foundation Layer)
> **Version:** 1.0.0
> **Last Updated:** 2026-02-24
> **Status:** Active

---

## 1. Purpose & Vision

The Bronze Tier is the **foundation** of the Personal AI Employee system. It establishes the minimum viable infrastructure that every higher tier (Silver, Gold, Platinum) builds on top of. A Bronze-compliant vault proves that a human and an AI agent can cooperate through a shared, file-based workspace with clear intake, action, completion, and audit cycles.

**Core promise:** Every piece of information that enters this vault is either acted upon, deferred with a reason, or archived — nothing disappears silently.

---

## 2. Hackathon Requirements (Bronze Tier)

### 2.1 Mandatory Deliverables

| # | Deliverable | Description |
|---|------------|-------------|
| B-01 | `Bronze-Constitution.md` | This document. Must exist at vault root. |
| B-02 | `Inbox/` folder | Capture zone for all raw input. |
| B-03 | `Needs_Action/` folder | Tasks the agent or human must act on. |
| B-04 | `Done/` folder | Completed and closed items. |
| B-05 | `Logs/` folder | Immutable audit trail of agent activity. |
| B-06 | `.claude/skills/` folder | Agent skill definitions (`.md` skill files). |
| B-07 | At least 1 Inbox note | Proof the intake pipeline works. |
| B-08 | At least 1 Skill file | Proof the agent has a defined capability. |
| B-09 | At least 1 Log entry | Proof the agent logs its own actions. |

### 2.2 Optional (Bonus Points at Bronze)

- `Templates/` folder with reusable note templates
- Daily note auto-generation
- Tag taxonomy defined in this constitution
- Dataview queries on any folder

---

## 3. Folder Rules

### 3.1 Inbox/
**Purpose:** The single entry point for all new information, tasks, ideas, and requests.

**Rules:**
- Any note dropped here has **not yet been triaged**.
- Notes MUST use the naming convention: `YYYY-MM-DD HH-MM — <short-title>.md`
- The agent checks `Inbox/` on every activation cycle.
- A note stays in `Inbox/` for a **maximum of 24 hours** before being promoted or deleted.
- No sub-folders inside `Inbox/`.
- Do NOT manually edit notes inside `Inbox/` — append only.

**Triage outcomes:**
- Promoted → `Needs_Action/` (requires a response or work)
- Promoted → `Done/` (already resolved, just archiving)
- Deleted → if duplicate or noise (agent must log the deletion reason)

### 3.2 Needs_Action/
**Purpose:** Active work queue. Every note here represents something that must happen.

**Rules:**
- Notes MUST include a `status:` frontmatter field with one of: `pending | in-progress | blocked | waiting`.
- Notes MUST include a `created:` and `due:` frontmatter field.
- The agent updates `status:` as work progresses.
- When status reaches **done**, the agent moves the note to `Done/` and logs the move.
- Sub-folders are allowed for grouping (e.g., `Needs_Action/Research/`, `Needs_Action/Writing/`).
- Notes are sorted by `due:` date ascending.

**Required frontmatter template:**
```yaml
---
title: ""
status: pending
priority: medium        # low | medium | high | critical
created: YYYY-MM-DD
due: YYYY-MM-DD
tags: []
agent_assigned: claude
---
```

### 3.3 Done/
**Purpose:** Immutable archive of completed work. Nothing is deleted from `Done/`.

**Rules:**
- Notes are moved here (never created directly here).
- Each note MUST have `completed:` frontmatter field added at move time.
- Sub-folders by year-month are allowed: `Done/2026-02/`.
- Never edit the body of a note once it is in `Done/`.
- The agent may append a `## Completion Summary` section at the bottom when closing.

**Required frontmatter added at close:**
```yaml
completed: YYYY-MM-DD
resolution: ""      # One sentence describing what was done
```

### 3.4 Logs/
**Purpose:** Append-only audit trail. The agent writes here; humans may read but not edit.

**Rules:**
- One log file per day, named `YYYY-MM-DD.md`.
- Each entry is a markdown table row or a timestamped bullet.
- Logs are **never deleted** (use `Logs/Archive/` to move old logs after 90 days).
- Every agent action (file create, move, edit, delete, skill execution) MUST produce a log entry.
- Log entries MUST include: timestamp, action type, source path, destination path (if any), outcome.

**Log entry format:**
```markdown
- `HH:MM:SS` | **ACTION_TYPE** | `source/path.md` → `dest/path.md` | ✅ success / ❌ failed | notes
```

**Action types:** `CREATE` `MOVE` `EDIT` `DELETE` `SKILL_RUN` `TRIAGE` `CLOSE` `ERROR`

---

## 4. Agent Skill System (.claude/skills/)

### 4.1 What is a Skill?
A Skill is a **named, reusable capability** defined as a Markdown file in `.claude/skills/`. Claude Code reads skill files to know what it is authorized and expected to do inside this vault.

### 4.2 Skill File Format
Each skill lives at `.claude/skills/<skill-name>.md` and must follow this schema:

```markdown
# Skill: <Name>
**ID:** skill-<kebab-case-id>
**Version:** 1.0.0
**Tier:** Bronze | Silver | Gold | Platinum
**Trigger:** <what activates this skill — user command or auto>

## Description
One paragraph describing what this skill does.

## Inputs
- `param1` (type, required/optional): description

## Outputs
- description of what is produced

## Steps
1. Step-by-step procedure the agent follows
2. ...

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Constraints
- What this skill must NOT do

## Log Requirement
What the agent must write to Logs/ when this skill runs.
```

### 4.3 Bronze-Tier Required Skills

| Skill File | Purpose |
|-----------|---------|
| `triage-inbox.md` | Reads Inbox/, categorizes, and moves notes |
| `log-action.md` | Writes a structured entry to today's log file |
| `close-task.md` | Moves a Needs_Action note to Done/ with summary |

---

## 5. Tagging Taxonomy (Bronze)

| Tag | Meaning |
|-----|---------|
| `#inbox` | Unprocessed, in intake |
| `#action` | Requires work |
| `#done` | Completed |
| `#log` | Log/audit note |
| `#skill` | Skill definition |
| `#constitution` | Governance document |
| `#blocked` | Waiting on external input |
| `#agent` | Written or modified by AI agent |
| `#human` | Written or modified by human |

---

## 6. Acceptance Criteria (Bronze Tier Checklist)

To pass Bronze Tier evaluation, **all** of the following must be true:

### 6.1 Structure Checks
- [ ] `Bronze-Constitution.md` exists at vault root
- [ ] `Inbox/` folder exists
- [ ] `Needs_Action/` folder exists
- [ ] `Done/` folder exists
- [ ] `Logs/` folder exists
- [ ] `.claude/skills/` folder exists

### 6.2 Content Checks
- [ ] At least 1 note exists in `Inbox/` with correct naming convention
- [ ] At least 1 note exists in `Needs_Action/` with required frontmatter
- [ ] At least 1 log file exists in `Logs/` with at least 1 entry
- [ ] At least 3 skill files exist in `.claude/skills/`

### 6.3 Behavior Checks
- [ ] Agent can triage an Inbox note (move to Needs_Action or Done)
- [ ] Agent logs every action it takes
- [ ] Agent can close a task (move from Needs_Action to Done)
- [ ] No note exists without a `title:` frontmatter field
- [ ] No note has been silently deleted (all deletions logged)

### 6.4 Quality Checks
- [ ] This constitution is complete and unmodified from spec
- [ ] No broken internal links
- [ ] All frontmatter fields are valid YAML (no tab indentation, proper quoting)
- [ ] Log entries follow the defined format

---

## 7. Upgrade Path

Once Bronze is certified:

| Tier | Unlocks |
|------|---------|
| **Silver** | Email/calendar integration, recurring task engine, multi-agent coordination |
| **Gold** | External API connections, web research skills, report generation |
| **Platinum** | Full autonomous employee loop, self-improvement, delegation to sub-agents |

Bronze is the prerequisite for all higher tiers. **Do not skip Bronze.**

---

## 8. Governance Rules

1. **This file is authoritative.** If a folder rule conflicts with a skill definition, this constitution wins.
2. **The agent must re-read this file** at the start of every session before taking any action.
3. **Humans may edit this constitution** but must increment the version and log the change.
4. **The agent must not create folders** outside the approved structure without logging a `CREATE` entry with justification.
5. **Silence is failure.** If the agent cannot complete an action, it must log an `ERROR` entry and surface the failure to the human.

---

## 9. Revision History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-02-24 | Claude (AI Employee) | Initial creation — Bronze Tier setup |

---

*This document governs the AI_Employee_Vault Bronze Tier implementation for the Personal AI Employee Hackathon 2026.*
