---
title: ""
type: plan
status: draft
priority: medium
created: YYYY-MM-DD
submitted: —
author: claude
tags: [plan, draft]
---

# Plan: <Title>

> **Status:** Draft  |  **Priority:** Medium  |  **Created:** YYYY-MM-DD  |  **Author:** Claude

---

## 1. Objective

*One clear paragraph. What will be true when this plan is successfully executed?*

---

## 2. Background & Context

*Why is this plan needed? What triggered it? What problem does it solve?*

---

## 3. Claude Reasoning Loop

> This section shows the agent's thinking process before proposing actions.

### 3.1 What I Know
- Fact or observation 1
- Fact or observation 2
- Fact or observation 3

### 3.2 What I Don't Know (Assumptions)
- Assumption 1 — needs human confirmation
- Assumption 2 — needs human confirmation

### 3.3 Constraints I'm Working Within
- Constraint from Bronze-Constitution or Silver-Constitution
- Time, resource, or scope constraint

### 3.4 Options Considered

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Option A | — | — | ❌ Rejected |
| Option B | — | — | ❌ Rejected |
| Option C (chosen) | — | — | ✅ Selected |

### 3.5 Why I Chose This Approach
*One paragraph explaining the reasoning behind the selected option.*

---

## 4. Proposed Actions

| Step | Action | Owner | Output |
|------|--------|-------|--------|
| 1 | — | claude | — |
| 2 | — | claude | — |
| 3 | — | human | — |

---

## 5. Resources Required

- **Files needed:** list any vault files to be read or modified
- **External access:** list any external systems (e.g. LinkedIn, calendar)
- **Human input:** describe what the human needs to provide or decide
- **Time estimate:** rough estimate of execution time

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| — | Low / Med / High | Low / Med / High | — |

---

## 7. Success Criteria

- [ ] Criterion 1 — measurable, specific
- [ ] Criterion 2 — measurable, specific
- [ ] Criterion 3 — measurable, specific

---

## 8. Timeline

| Phase | Target Date | Owner | Status |
|-------|------------|-------|--------|
| Draft complete | YYYY-MM-DD | claude | ⬜ |
| Submitted for approval | YYYY-MM-DD | claude | ⬜ |
| Human review | YYYY-MM-DD | human | ⬜ |
| Execution begins | YYYY-MM-DD | claude | ⬜ |
| Execution complete | YYYY-MM-DD | claude | ⬜ |

---

## 9. Questions for Human Reviewer

> *Claude lists anything that needs human input before or during execution.*

1. Question 1?
2. Question 2?

---

## 10. Agent Notes

*Any additional context, edge cases, or observations the human should know.*

---

## 11. Approval Section

> *Filled in by human when moving to Approved/ or Rejected/.*

```yaml
# On approval — add to frontmatter:
approved_by: human
approved_date: YYYY-MM-DD
status: approved

# On rejection — add to frontmatter:
rejected_by: human
rejected_date: YYYY-MM-DD
rejection_reason: ""
status: rejected
```

---

## 12. Completion Summary

> *Filled in by agent when plan is fully executed and moved to Done/.*

**Executed by:** Claude
**Completed:** YYYY-MM-DD
**Outcome:** —
**Deviations from plan:** None / describe any deviations

---

## Usage Instructions

> *Remove this section when using the template for a real plan.*

1. Copy this file to `Plans/` with name `YYYY-MM-DD — Your-Plan-Title.md`
2. Fill in all sections — delete any that are not applicable
3. Work through Section 3 (Reasoning Loop) carefully before proposing actions
4. Tell Claude: `submit plan <filename>` when ready for human review
5. Human says `approve plan <filename>` or `reject plan <filename>`
6. On approval, Claude executes and moves completed plan to `Done/`

**For LinkedIn posts**, also fill in:
```yaml
type: linkedin-post
topic: ""
tone: professional
target_audience: ""
call_to_action: ""
```

---

*Plan-Template.md — Silver Tier | AI_Employee_Vault | Personal AI Employee Hackathon 2026*
*Governed by: [[Silver-Constitution]] and [[Bronze-Constitution]]*
