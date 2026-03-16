---
title: "Silver-Constitution"
tier: Silver
version: 1.0.0
created: 2026-02-24
prerequisite: Bronze-Constitution.md
tags: [constitution, silver, governance]
---

# Silver-Constitution
## Personal AI Employee Hackathon 2026 — Silver Tier

> **Tier:** Silver (Approval & Planning Layer)
> **Version:** 1.0.0
> **Prerequisite:** Bronze Tier fully certified
> **Last Updated:** 2026-02-24
> **Status:** Active

---

## 1. Purpose & Vision

Silver Tier extends the Bronze foundation by adding an **approval workflow**, a **planning layer**, and a **proposal lifecycle**. Whereas Bronze captures and processes raw tasks, Silver introduces structured decision-making: the agent can now draft plans, submit them for human review, and route the outcome into Approved or Rejected pipelines.

**Core promise:** No consequential action is taken without a human approval step. Every plan is traceable from draft to decision.

---

## 2. Tier Prerequisite

Silver Tier **requires** a fully certified Bronze Tier vault. Before activating Silver:

- [ ] `Bronze-Constitution.md` exists and is complete
- [ ] All Bronze folders exist: `Inbox/`, `Needs_Action/`, `Done/`, `Logs/`
- [ ] `.claude/skills/` contains at minimum 3 Bronze skill files
- [ ] `watcher/filesystem_watcher.py` is functional
- [ ] Bronze acceptance criteria (Section 6 of Bronze-Constitution) are all met

**Do not proceed with Silver setup if Bronze is not certified.**

---

## 3. Silver Tier Mandatory Deliverables

| # | Deliverable | Description |
|---|------------|-------------|
| S-01 | `Silver-Constitution.md` | This document. Must exist at vault root. |
| S-02 | `Plans/` folder | Drafts and proposals created by the agent |
| S-03 | `Pending_Approval/` folder | Plans submitted to the human for review |
| S-04 | `Approved/` folder | Plans approved by the human |
| S-05 | `Rejected/` folder | Plans rejected by the human, with reason |
| S-06 | At least 1 Silver skill file | In `.claude/skills/` |
| S-07 | At least 1 complete plan lifecycle | Draft → Pending → Approved/Rejected, all logged |

---

## 4. Folder Rules

### 4.1 Plans/
**Purpose:** The agent's drafting workspace. All new plans, proposals, and structured documents start here.

**Rules:**
- Plans are created by the agent in response to a task or instruction.
- Naming convention: `YYYY-MM-DD — <Plan-Title>.md`
- Every plan MUST use the Silver Plan Template (see Section 6).
- A plan in `Plans/` is a **draft** — it has not been reviewed by the human.
- The agent may edit plans in `Plans/` freely until submission.
- When ready for review, the agent moves the plan to `Pending_Approval/`.
- No sub-folders inside `Plans/`.

**Required frontmatter:**
```yaml
---
title: ""
type: plan
status: draft
created: YYYY-MM-DD
author: claude
tags: [plan, draft]
---
```

### 4.2 Pending_Approval/
**Purpose:** Plans that have been submitted to the human and are awaiting a decision.

**Rules:**
- Only the agent moves plans **into** `Pending_Approval/` (from `Plans/`).
- Only the human moves plans **out** of `Pending_Approval/` (to `Approved/` or `Rejected/`).
- The agent must NOT auto-approve its own plans.
- Plans MUST have `status: pending-approval` when in this folder.
- The agent checks `Pending_Approval/` at each session and alerts the human if any plan has waited more than 48 hours.
- No sub-folders inside `Pending_Approval/`.

**Required frontmatter:**
```yaml
---
title: ""
type: plan
status: pending-approval
created: YYYY-MM-DD
submitted: YYYY-MM-DD
author: claude
awaiting_review_by: human
tags: [plan, pending]
---
```

### 4.3 Approved/
**Purpose:** Immutable archive of human-approved plans. These become the basis for action.

**Rules:**
- Plans are moved here by the human (or by the agent on explicit human instruction).
- Each plan must have `status: approved` and `approved_by:` and `approved_date:` frontmatter fields.
- Once in `Approved/`, a plan's content is frozen — no edits.
- Sub-folders by year-month are allowed: `Approved/2026-02/`
- The agent reads `Approved/` plans as authoritative instructions.
- Approved plans that have been fully executed should be moved to `Done/`.

**Required frontmatter added at approval:**
```yaml
approved_by: human
approved_date: YYYY-MM-DD
status: approved
```

### 4.4 Rejected/
**Purpose:** Archive of human-rejected plans, preserved for learning and audit.

**Rules:**
- Plans are moved here by the human (or by the agent on explicit human instruction).
- Each plan must have `status: rejected`, `rejected_by:`, `rejected_date:`, and `rejection_reason:` fields.
- Rejected plans are **never deleted** — they serve as audit trail and learning data.
- Sub-folders by year-month are allowed: `Rejected/2026-02/`
- The agent reads rejection reasons and incorporates them into future plans.

**Required frontmatter added at rejection:**
```yaml
rejected_by: human
rejected_date: YYYY-MM-DD
rejection_reason: ""
status: rejected
```

---

## 5. Plan Lifecycle

```
Agent receives instruction or identifies need
              ↓
Agent drafts plan → Plans/  (status: draft)
              ↓
Agent reviews, refines, finalises draft
              ↓
Agent submits → Pending_Approval/  (status: pending-approval)
              ↓
Human reviews (48-hour SLA)
       ↙              ↘
Approved/           Rejected/
(status: approved)  (status: rejected + reason)
       ↓
Agent executes approved plan
       ↓
Completed items → Done/
       ↓
Log entries written throughout
```

---

## 6. Silver Plan Template

Every file created in `Plans/` must follow this template:

```markdown
---
title: ""
type: plan
status: draft
created: YYYY-MM-DD
author: claude
priority: medium
tags: [plan, draft]
---

# Plan: <Title>

## Objective
One paragraph describing what this plan aims to achieve.

## Background
Why this plan is needed. What triggered it.

## Proposed Actions
1. Step one — description
2. Step two — description
3. Step three — description

## Resources Required
- List any files, tools, time, or human input required

## Risks & Mitigations
| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| example risk | low | example mitigation |

## Success Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Timeline
| Phase | Target Date | Owner |
|-------|------------|-------|
| Draft complete | YYYY-MM-DD | claude |
| Human approval | YYYY-MM-DD | human |
| Execution | YYYY-MM-DD | claude |

## Agent Notes
Any notes, assumptions, or questions for the human reviewer.
```

---

## 7. Silver Tier Agent Skill Requirements

### 7.1 Required Silver Skills

| Skill File | Purpose |
|-----------|---------|
| `create-plan.md` | Draft a structured plan in `Plans/` |
| `submit-for-approval.md` | Move plan from `Plans/` to `Pending_Approval/` |
| `check-approvals.md` | Read `Approved/` and queue execution of approved plans |

### 7.2 Skill Location
All Silver skills are placed in `.claude/skills/` alongside Bronze skills. Silver skills must declare `**Tier:** Silver` in their header.

---

## 8. Approval Workflow Rules

| Rule | Description |
|------|-------------|
| A-01 | The agent MUST NOT execute any plan that has not passed through `Approved/` |
| A-02 | The agent MUST alert the human when a plan has been in `Pending_Approval/` for more than 48 hours |
| A-03 | The human's decision is final — the agent does not dispute approvals or rejections |
| A-04 | The agent reads `rejection_reason:` from `Rejected/` and improves future plans accordingly |
| A-05 | The agent logs every state transition (draft→pending, pending→approved, pending→rejected) |
| A-06 | A plan may be recalled from `Pending_Approval/` back to `Plans/` for revision (human or agent instruction) |
| A-07 | The agent may not approve its own plans even if explicitly asked — it must surface the request to the human |

---

## 9. Logging Requirements (Silver Tier)

Silver Tier adds the following action types to the Bronze log format:

| Action Type | When Used |
|------------|-----------|
| `PLAN_CREATE` | Agent creates a new draft in `Plans/` |
| `PLAN_SUBMIT` | Agent moves plan to `Pending_Approval/` |
| `PLAN_APPROVE` | Human approves — plan moves to `Approved/` |
| `PLAN_REJECT` | Human rejects — plan moves to `Rejected/` |
| `PLAN_RECALL` | Plan recalled from `Pending_Approval/` to `Plans/` |
| `PLAN_EXECUTE` | Agent begins executing an approved plan |

All entries use the same format as Bronze:
```
- `HH:MM:SS` | **ACTION_TYPE** | `source/path.md` → `dest/path.md` | ✅ success / ❌ failed | notes
```

---

## 10. Acceptance Criteria (Silver Tier Checklist)

To pass Silver Tier evaluation, **all** of the following must be true:

### 10.1 Prerequisite Check
- [ ] Bronze Tier fully certified (all Bronze acceptance criteria met)

### 10.2 Structure Checks
- [ ] `Silver-Constitution.md` exists at vault root
- [ ] `Plans/` folder exists
- [ ] `Pending_Approval/` folder exists
- [ ] `Approved/` folder exists
- [ ] `Rejected/` folder exists

### 10.3 Content Checks
- [ ] At least 1 Silver skill file in `.claude/skills/`
- [ ] At least 1 complete plan lifecycle completed (draft → approved or rejected)
- [ ] All plan files use the Silver Plan Template

### 10.4 Behavior Checks
- [ ] Agent can create a plan in `Plans/`
- [ ] Agent can submit a plan to `Pending_Approval/`
- [ ] Agent DOES NOT self-approve plans
- [ ] Agent reads `Approved/` plans before acting
- [ ] Agent reads rejection reasons from `Rejected/`
- [ ] All plan state transitions are logged with correct Silver action types

### 10.5 Quality Checks
- [ ] All frontmatter fields are valid YAML
- [ ] No plan exists without `title:` and `status:` fields
- [ ] No plan was auto-approved without human review
- [ ] Rejection reasons are non-empty strings

---

## 11. Upgrade Path

| From | To | Requirement |
|------|----|------------|
| Bronze | **Silver** | This constitution + 4 new folders + 3 Silver skills + 1 complete plan lifecycle |
| **Silver** | Gold | External API connections, web research, report generation |
| Gold | Platinum | Full autonomous loop, self-improvement, delegation |

---

## 12. Governance Rules

1. **Bronze-Constitution.md remains authoritative** for all Bronze-layer rules. Silver does not override Bronze.
2. **This file governs the Silver layer only.** In case of conflict, Bronze rules take precedence for shared concerns.
3. **The agent re-reads both constitutions** (`Bronze-Constitution.md` and `Silver-Constitution.md`) at the start of every session.
4. **Humans may edit this constitution** but must increment the version and log the change with action type `EDIT`.
5. **The approval gate is non-negotiable.** No Silver-tier action proceeds without an `Approved/` entry.

---

## 13. Revision History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-02-24 | Claude (AI Employee) | Initial creation — Silver Tier setup |

---

*This document governs the AI_Employee_Vault Silver Tier implementation for the Personal AI Employee Hackathon 2026.*
*Prerequisite: [[Bronze-Constitution]]*
