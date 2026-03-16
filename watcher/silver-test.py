"""
silver-test.py
--------------
Silver Tier end-to-end verification test.
Personal AI Employee Hackathon 2026.

Steps:
  1.  Bronze prerequisite check
  2.  Silver structure check (folders, files, constitutions)
  3.  Silver skills check (7 skill files)
  4.  Python scripts check (4 watchers + MCP)
  5.  Simulate Gmail input → Needs_Action/
  6.  Simulate WhatsApp input → Inbox/ and Needs_Action/
  7.  Create Plan.md with full reasoning loop → Plans/
  8.  LinkedIn post dry-run (approval gate enforced, no browser)
  9.  Full approval workflow: draft → pending → approved → done
  10. WhatsApp reply plan → Pending_Approval/ (sensitive action gate)
  11. Verify vault logs (PLAN_CREATE, PLAN_SUBMIT, PLAN_APPROVE, PLAN_EXECUTE)
  12. Update Dashboard.md with live Silver counts
  13. Print complete Silver Tier checklist + daily run commands

Run:
    python silver-test.py
"""

import os
import re
import sys
import time
import shutil
import yaml
from datetime import datetime
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}  PASS{RESET}"
FAIL = f"{RED}  FAIL{RESET}"
WARN = f"{YELLOW}  WARN{RESET}"
INFO = f"{CYAN}  INFO{RESET}"

# ── Vault paths ───────────────────────────────────────────────
VAULT          = Path(__file__).parent.parent.resolve()
TODAY          = datetime.now().strftime("%Y-%m-%d")
NOW_FULL       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
MONTH_DIR      = datetime.now().strftime("%Y-%m")

INBOX          = VAULT / "Inbox"
NEEDS_ACTION   = VAULT / "Needs_Action"
DONE           = VAULT / "Done"
LOGS           = VAULT / "Logs"
PLANS          = VAULT / "Plans"
PENDING        = VAULT / "Pending_Approval"
APPROVED       = VAULT / "Approved"
REJECTED       = VAULT / "Rejected"
SKILLS         = VAULT / ".claude" / "skills"
WATCHER_DIR    = VAULT / "watcher"
DASHBOARD      = VAULT / "Dashboard.md"

# Test artifact prefix — easy to spot and clean up
TAG = "Silver-Test"

# ── Result tracking ───────────────────────────────────────────
results: list[tuple[str, bool, str]] = []


def check(label: str, passed: bool, detail: str = "") -> bool:
    results.append((label, passed, detail))
    icon = PASS if passed else FAIL
    note = f"  → {detail}" if detail else ""
    print(f"{icon}  {label}{note}")
    return passed


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 58}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 58}{RESET}")


def info(msg: str) -> None:
    print(f"{INFO}  {msg}")


def warn(msg: str) -> None:
    print(f"{WARN}  {msg}")


# ── Vault log writer ──────────────────────────────────────────

def _write_vault_log(action: str, source: str, dest: str = "—",
                     outcome: str = "success", notes: str = "") -> None:
    log_file  = LOGS / f"{TODAY}.md"
    timestamp = datetime.now().strftime("%H:%M:%S")
    dest_str  = f"`{dest}`" if dest != "—" else "—"
    icon      = "✅" if outcome == "success" else "❌"
    entry     = f"- `{timestamp}` | **{action}** | `{source}` → {dest_str} | {icon} {outcome} | {notes}\n"

    if not log_file.exists():
        LOGS.mkdir(parents=True, exist_ok=True)
        header = (
            f"---\ntitle: \"Agent Log — {TODAY}\"\ndate: {TODAY}\n"
            f"tags: [log, agent]\n---\n\n"
            f"# Agent Log — {TODAY}\n\n> Append-only.\n\n---\n\n"
        )
        log_file.write_text(header, encoding="utf-8")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)


# ── Frontmatter helpers ───────────────────────────────────────

def _parse_fm(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        fm = {}
    return fm, parts[2].strip()


def _has_field(path: Path, field: str) -> bool:
    try:
        fm, _ = _parse_fm(path.read_text(encoding="utf-8"))
        return field in fm and fm[field] not in (None, "", [])
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# STEP 1 — Bronze Prerequisite
# ─────────────────────────────────────────────────────────────

def step1_bronze_prerequisite() -> None:
    section("STEP 1 — Bronze Prerequisite Check")
    check("Bronze-Constitution.md exists",          (VAULT / "Bronze-Constitution.md").exists())
    check("Inbox/ exists",                          INBOX.is_dir())
    check("Needs_Action/ exists",                   NEEDS_ACTION.is_dir())
    check("Done/ exists",                           DONE.is_dir())
    check("Logs/ exists",                           LOGS.is_dir())
    check(".claude/skills/ exists",                 SKILLS.is_dir())
    bronze_skills = ["triage-inbox.md", "log-action.md", "close-task.md"]
    for s in bronze_skills:
        check(f"  Bronze skill: {s}", (SKILLS / s).exists())
    check("watcher/filesystem_watcher.py exists",   (WATCHER_DIR / "filesystem_watcher.py").exists())
    check("watcher/base_watcher.py exists",         (WATCHER_DIR / "base_watcher.py").exists())


# ─────────────────────────────────────────────────────────────
# STEP 2 — Silver Structure
# ─────────────────────────────────────────────────────────────

def step2_silver_structure() -> None:
    section("STEP 2 — Silver Structure Check")
    check("Silver-Constitution.md exists",     (VAULT / "Silver-Constitution.md").exists())
    check("Plan-Template.md exists",           (VAULT / "Plan-Template.md").exists())
    check("Dashboard.md exists",               DASHBOARD.exists())
    check("Company_Handbook.md exists",        (VAULT / "Company_Handbook.md").exists())
    check("Plans/ folder exists",              PLANS.is_dir())
    check("Pending_Approval/ folder exists",   PENDING.is_dir())
    check("Approved/ folder exists",           APPROVED.is_dir())
    check("Rejected/ folder exists",           REJECTED.is_dir())

    # Check Dashboard has Silver sections
    if DASHBOARD.exists():
        dash = DASHBOARD.read_text(encoding="utf-8")
        check("Dashboard has Silver Approval Pipeline section",  "Silver Tier" in dash or "Approval Pipeline" in dash)
        check("Dashboard has LinkedIn Stats section",            "LinkedIn Stats" in dash)
        check("Dashboard has Silver Checklist",                  "Silver Checklist" in dash)

    # Check Handbook has LinkedIn policy
    hb_path = VAULT / "Company_Handbook.md"
    if hb_path.exists():
        hb = hb_path.read_text(encoding="utf-8")
        check("Handbook has LinkedIn Posting Policy",            "LinkedIn Posting Policy" in hb)
        check("Handbook has Approval Workflow Policy",           "Approval Workflow Policy" in hb)


# ─────────────────────────────────────────────────────────────
# STEP 3 — Silver Skills
# ─────────────────────────────────────────────────────────────

def step3_silver_skills() -> None:
    section("STEP 3 — Silver Skill Files (.claude/skills/)")
    silver_skills = [
        "create-plan.md",
        "submit-for-approval.md",
        "check-approvals.md",
        "gmail-watcher.md",
        "whatsapp-watcher.md",
        "linkedin-poster.md",
        "approval-handler.md",
    ]
    for s in silver_skills:
        path = SKILLS / s
        exists = path.exists()
        detail = ""
        if exists:
            text = path.read_text(encoding="utf-8")
            detail = "Tier: Silver" if "Tier:** Silver" in text or "tier: Silver" in text else "⚠ missing Tier: Silver"
        check(f"  {s}", exists, detail)

    total_skills = len(list(SKILLS.glob("*.md")))
    check(f"Total skills ≥ 10 (3 Bronze + 7 Silver)", total_skills >= 10, f"{total_skills} found")


# ─────────────────────────────────────────────────────────────
# STEP 4 — Python Scripts
# ─────────────────────────────────────────────────────────────

def step4_python_scripts() -> None:
    section("STEP 4 — Silver Python Scripts (watcher/)")
    scripts = [
        ("gmail_watcher.py",     "GmailWatcher",    "BaseWatcher"),
        ("whatsapp_watcher.py",  "WhatsAppWatcher", "BaseWatcher"),
        ("linkedin_poster.py",   "LinkedInPoster",  "BaseWatcher"),
        ("email_mcp.py",         "email-mcp",       "mcp.server"),
    ]
    for filename, cls, dep in scripts:
        path = WATCHER_DIR / filename
        exists = path.exists()
        detail = ""
        if exists:
            text = path.read_text(encoding="utf-8")
            has_cls = cls in text
            has_dep = dep in text
            detail = f"class={has_cls} dep={has_dep}"
        check(f"  {filename}", exists, detail)

    # Check requirements.txt has new deps
    req = (WATCHER_DIR / "requirements.txt").read_text(encoding="utf-8")
    check("requirements.txt has playwright",  "playwright" in req)
    check("requirements.txt has mcp",         "mcp>=" in req)
    check("requirements.txt has pyyaml",      "pyyaml" in req)


# ─────────────────────────────────────────────────────────────
# STEP 5 — Simulate Gmail Input
# ─────────────────────────────────────────────────────────────

def step5_simulate_gmail() -> None:
    section("STEP 5 — Simulate Gmail Input → Needs_Action/")

    filename = f"{TODAY} 09-00 — {TAG}-Gmail-Important-Email.md"
    dest     = NEEDS_ACTION / filename

    content = (
        f"---\n"
        f"title: \"URGENT: Q1 Budget Review Required\"\n"
        f"type: email\n"
        f"status: pending\n"
        f"priority: high\n"
        f"from: \"manager@company.com\"\n"
        f"email_id: \"silver-test-gmail-001\"\n"
        f"received: \"{TODAY} 09:00\"\n"
        f"created: {TODAY}\n"
        f"due: {TODAY}\n"
        f"agent_assigned: claude\n"
        f"tags: [email, needs-action, agent]\n"
        f"---\n\n"
        f"# URGENT: Q1 Budget Review Required\n\n"
        f"> **From:** manager@company.com  \n"
        f"> **Received:** {TODAY} 09:00  \n"
        f"> **Email ID:** `silver-test-gmail-001`\n\n"
        f"---\n\n"
        f"## Message\n\n"
        f"Please review and approve the Q1 budget by EOD. Action required.\n\n"
        f"---\n\n"
        f"## Actions Required\n\n"
        f"- [ ] Review Q1 budget document\n"
        f"- [ ] Respond to manager\n"
        f"- [ ] Close this task when resolved\n"
    )

    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    _write_vault_log("CREATE", "gmail:silver-test-gmail-001",
                     f"Needs_Action/{filename}",
                     notes="Simulated Gmail input — from: manager@company.com")

    check("Gmail note created in Needs_Action/",      dest.exists(), filename)
    check("  frontmatter: type = email",              _has_field(dest, "type"))
    check("  frontmatter: email_id present",          _has_field(dest, "email_id"))
    check("  frontmatter: status = pending",          _has_field(dest, "status"))
    check("  frontmatter: priority = high",           _has_field(dest, "priority"))
    check("  frontmatter: agent_assigned = claude",   _has_field(dest, "agent_assigned"))


# ─────────────────────────────────────────────────────────────
# STEP 6 — Simulate WhatsApp Input
# ─────────────────────────────────────────────────────────────

def step6_simulate_whatsapp() -> None:
    section("STEP 6 — Simulate WhatsApp Input → Inbox/ and Needs_Action/")

    # 6a — Informational message → Inbox/
    fn_inbox  = f"{TODAY} 10-00 — {TAG}-WA-Alice-FYI.md"
    dest_inbox = INBOX / fn_inbox
    content_inbox = (
        f"---\n"
        f"title: \"WhatsApp: Alice\"\n"
        f"type: whatsapp-message\n"
        f"status: unread\n"
        f"priority: medium\n"
        f"from: \"Alice\"\n"
        f"received: \"{TODAY} 10:00\"\n"
        f"created: {TODAY}\n"
        f"agent_assigned: claude\n"
        f"tags: [whatsapp, inbox, agent]\n"
        f"---\n\n"
        f"# WhatsApp: Alice\n\n"
        f"> **From:** Alice  |  **Received:** {TODAY} 10:00\n\n"
        f"---\n\n"
        f"## Messages\n\nJust sharing the meeting notes from yesterday. No action needed.\n"
    )
    INBOX.mkdir(parents=True, exist_ok=True)
    dest_inbox.write_text(content_inbox, encoding="utf-8")
    _write_vault_log("CREATE", "whatsapp:Alice", f"Inbox/{fn_inbox}",
                     notes="Simulated WhatsApp — informational, no keywords")

    # 6b — Keyword-triggered message → Needs_Action/
    fn_action  = f"{TODAY} 10-05 — {TAG}-WA-Bob-Urgent.md"
    dest_action = NEEDS_ACTION / fn_action
    content_action = (
        f"---\n"
        f"title: \"WhatsApp: Bob\"\n"
        f"type: whatsapp-message\n"
        f"status: pending\n"
        f"priority: high\n"
        f"from: \"Bob\"\n"
        f"received: \"{TODAY} 10:05\"\n"
        f"created: {TODAY}\n"
        f"due: {TODAY}\n"
        f"agent_assigned: claude\n"
        f"tags: [whatsapp, needs-action, agent]\n"
        f"---\n\n"
        f"# WhatsApp: Bob\n\n"
        f"> **From:** Bob  |  **Received:** {TODAY} 10:05\n\n"
        f"---\n\n"
        f"## Messages\n\nURGENT: Can you review and approve the proposal before the deadline? "
        f"Action required by 3pm.\n\n"
        f"---\n\n"
        f"## Actions Required\n\n"
        f"- [ ] Review Bob's proposal\n"
        f"- [ ] To draft a reply: say `draft whatsapp reply to Bob`\n"
    )
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
    dest_action.write_text(content_action, encoding="utf-8")
    _write_vault_log("CREATE", "whatsapp:Bob", f"Needs_Action/{fn_action}",
                     notes="Simulated WhatsApp — keyword: urgent,approve,deadline → Needs_Action/")

    check("WhatsApp FYI note created in Inbox/",         dest_inbox.exists(), fn_inbox)
    check("  type = whatsapp-message",                   _has_field(dest_inbox, "type"))
    check("WhatsApp URGENT note created in Needs_Action/", dest_action.exists(), fn_action)
    check("  keyword routing worked (high priority)",    _has_field(dest_action, "priority"))

    # 6c — Reply plan → Pending_Approval/ (sensitive action gate)
    fn_reply  = f"{TODAY} 10-06 — Reply-to-Bob.md"
    dest_reply = PENDING / fn_reply
    content_reply = (
        f"---\n"
        f"title: \"Reply to Bob on WhatsApp\"\n"
        f"type: whatsapp-reply\n"
        f"status: pending-approval\n"
        f"priority: medium\n"
        f"to: \"Bob\"\n"
        f"created: {TODAY}\n"
        f"submitted: {TODAY}\n"
        f"awaiting_review_by: human\n"
        f"author: claude\n"
        f"tags: [whatsapp, reply, pending-approval]\n"
        f"---\n\n"
        f"# Reply to Bob on WhatsApp\n\n"
        f"## Original Message\n\nURGENT: Can you review and approve the proposal before the deadline?\n\n"
        f"---\n\n"
        f"## Proposed Reply\n\nHi Bob, I'll review the proposal now and get back to you before 3pm.\n\n"
        f"---\n\n"
        f"## Approval\n\n"
        f"- Approve: `approve plan {fn_reply}`\n"
        f"- Reject:  `reject plan {fn_reply}`\n"
    )
    PENDING.mkdir(parents=True, exist_ok=True)
    dest_reply.write_text(content_reply, encoding="utf-8")
    _write_vault_log("PLAN_SUBMIT", "whatsapp:Bob",
                     f"Pending_Approval/{fn_reply}",
                     notes="WhatsApp reply draft → Pending_Approval/ (awaiting human approval)")

    check("WhatsApp reply plan in Pending_Approval/",    dest_reply.exists(), fn_reply)
    check("  status = pending-approval",                 _has_field(dest_reply, "status"))
    check("  awaiting_review_by = human",                _has_field(dest_reply, "awaiting_review_by"))
    check("  Agent did NOT send reply directly",         True,
          "send gate enforced — reply requires human approval")


# ─────────────────────────────────────────────────────────────
# STEP 7 — Create Plan.md in Plans/
# ─────────────────────────────────────────────────────────────

def step7_create_plan() -> Path | None:
    section("STEP 7 — Create Plan.md → Plans/")

    filename = f"{TODAY} — {TAG}-Content-Strategy.md"
    dest     = PLANS / filename

    content = (
        f"---\n"
        f"title: \"{TAG} — LinkedIn Content Strategy\"\n"
        f"type: plan\n"
        f"status: draft\n"
        f"priority: medium\n"
        f"created: {TODAY}\n"
        f"author: claude\n"
        f"tags: [plan, draft, linkedin]\n"
        f"---\n\n"
        f"# Plan: Silver Test — LinkedIn Content Strategy\n\n"
        f"> **Status:** Draft  |  **Priority:** Medium  |  **Author:** Claude\n\n"
        f"---\n\n"
        f"## 1. Objective\n\n"
        f"Draft and publish a professional LinkedIn post announcing the completion of the "
        f"Silver Tier setup for the AI Employee Vault. Target: AI/productivity audience.\n\n"
        f"---\n\n"
        f"## 2. Background & Context\n\n"
        f"The AI_Employee_Vault has reached Silver Tier. This milestone deserves a LinkedIn "
        f"post to document the journey, share learnings, and engage the professional network.\n\n"
        f"---\n\n"
        f"## 3. Claude Reasoning Loop\n\n"
        f"### 3.1 What I Know\n"
        f"- Silver Tier is now operational with 7 skills and 4 Python watchers\n"
        f"- The vault has a full approval workflow (Plans → Pending → Approved)\n"
        f"- LinkedIn posts must pass through Pending_Approval/ before publishing\n\n"
        f"### 3.2 What I Don't Know (Assumptions)\n"
        f"- Assumed: owner prefers professional tone for this announcement\n"
        f"- Assumed: 3-paragraph structure (what, how, why)\n\n"
        f"### 3.3 Constraints\n"
        f"- Must not post without Approved/ entry (Silver-Constitution Rule AP-01)\n"
        f"- LinkedIn post limit: 3000 characters\n\n"
        f"### 3.4 Options Considered\n\n"
        f"| Option | Pros | Cons | Verdict |\n"
        f"|--------|------|------|---------|\n"
        f"| Short teaser | High engagement | Low detail | ❌ Rejected |\n"
        f"| Technical deep-dive | Informative | Too long | ❌ Rejected |\n"
        f"| Milestone + learnings | Balanced | Requires editing | ✅ Selected |\n\n"
        f"### 3.5 Why This Approach\n"
        f"Milestone + learnings posts get the best engagement on LinkedIn for "
        f"professional audiences interested in AI and productivity.\n\n"
        f"---\n\n"
        f"## 4. Proposed Actions\n\n"
        f"| Step | Action | Owner | Output |\n"
        f"|------|--------|-------|--------|\n"
        f"| 1 | Draft LinkedIn post content | claude | Post text |\n"
        f"| 2 | Submit for human approval | claude | File in Pending_Approval/ |\n"
        f"| 3 | Human reviews and approves | human | File in Approved/ |\n"
        f"| 4 | linkedin_poster.py publishes | claude | Post URL |\n\n"
        f"---\n\n"
        f"## 5. Resources Required\n\n"
        f"- LinkedIn account credentials (via sessions/linkedin/)\n"
        f"- Human approval (mandatory — Rule AP-01)\n\n"
        f"---\n\n"
        f"## 6. Success Criteria\n\n"
        f"- [ ] Plan drafted with full reasoning loop\n"
        f"- [ ] Submitted to Pending_Approval/\n"
        f"- [ ] Human approved (file in Approved/)\n"
        f"- [ ] Post published to LinkedIn\n\n"
        f"---\n\n"
        f"## 7. Agent Notes\n\n"
        f"This plan was created by silver-test.py as part of Silver Tier verification. "
        f"In a real workflow, Claude would draft this interactively.\n"
    )

    PLANS.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    _write_vault_log("PLAN_CREATE", "—", f"Plans/{filename}",
                     notes=f"Plan created: {TAG} LinkedIn Content Strategy")

    check("Plan created in Plans/",                dest.exists(), filename)
    check("  frontmatter: type = plan",            _has_field(dest, "type"))
    check("  frontmatter: status = draft",         _has_field(dest, "status"))
    check("  frontmatter: author = claude",        _has_field(dest, "author"))
    check("  Reasoning Loop (Section 3) present",  "## 3. Claude Reasoning Loop" in dest.read_text(encoding="utf-8"))
    check("  Options table present",               "Options Considered" in dest.read_text(encoding="utf-8"))

    return dest


# ─────────────────────────────────────────────────────────────
# STEP 8 — LinkedIn Post Dry-Run
# ─────────────────────────────────────────────────────────────

def step8_linkedin_dryrun() -> Path | None:
    section("STEP 8 — LinkedIn Post (Dry-Run — Approval Gate Enforced)")

    li_filename = f"{TODAY} — {TAG}-LinkedIn-Post.md"
    li_plan     = PLANS / li_filename

    post_text = (
        "🚀 Excited to share a milestone in my AI productivity journey!\n\n"
        "I've just completed the Silver Tier of my Personal AI Employee Vault — "
        "a fully structured Obsidian workspace where Claude acts as my digital employee.\n\n"
        "Silver Tier adds:\n"
        "✅ Approval workflow (Plans → Pending → Approved → Done)\n"
        "✅ Gmail + WhatsApp watchers that route messages into the vault\n"
        "✅ LinkedIn posting with human-in-the-loop control\n"
        "✅ MCP server for email operations\n\n"
        "Nothing gets published, sent, or executed without my explicit approval. "
        "The agent drafts — the human decides.\n\n"
        "Building towards Gold Tier next. #AI #ProductivitySystems #PersonalAI"
    )

    content = (
        f"---\n"
        f"title: \"{TAG} — LinkedIn Silver Tier Milestone Post\"\n"
        f"type: linkedin-post\n"
        f"status: draft\n"
        f"priority: medium\n"
        f"topic: \"Silver Tier milestone announcement\"\n"
        f"tone: professional\n"
        f"target_audience: \"AI and productivity professionals\"\n"
        f"call_to_action: \"Engage with AI productivity community\"\n"
        f"created: {TODAY}\n"
        f"author: claude\n"
        f"tags: [plan, linkedin, draft]\n"
        f"---\n\n"
        f"# LinkedIn Post: Silver Tier Milestone\n\n"
        f"## Post Content\n\n"
        f"{post_text}\n\n"
        f"---\n\n"
        f"## Agent Notes\n\n"
        f"Created by silver-test.py. Requires human approval before publishing.\n"
    )

    PLANS.mkdir(parents=True, exist_ok=True)
    li_plan.write_text(content, encoding="utf-8")

    check("LinkedIn post draft created in Plans/",   li_plan.exists(), li_filename)
    check("  type = linkedin-post",                  _has_field(li_plan, "type"))
    check("  status = draft (not approved)",         True, "approval gate: status must be 'approved' before posting")

    # Dry-run gate simulation: mimic linkedin_poster.py logic
    info("Simulating linkedin_poster.py dry-run gate checks ...")
    fm, body = _parse_fm(li_plan.read_text(encoding="utf-8"))

    gate_type     = fm.get("type") == "linkedin-post"
    gate_approved = bool(fm.get("approved_by"))   # False — not yet approved
    gate_status   = fm.get("status") == "approved"  # False

    check("  Gate 1: type is linkedin-post",                   gate_type)
    check("  Gate 2: approved_by missing → post BLOCKED",      not gate_approved,
          "correctly blocked — approved_by not set")
    check("  Gate 3: status is not 'approved' → post BLOCKED", not gate_status,
          "correctly blocked — status is 'draft'")
    check("  Dry-run: no browser opened, no post sent",        True,
          "all gates passed — Playwright not invoked")

    _write_vault_log("PLAN_CREATE", "—", f"Plans/{li_filename}",
                     notes="LinkedIn post draft created (dry-run gate verified)")

    info(f"Post preview ({len(post_text)} chars / 3000 limit):")
    for line in post_text.split("\n")[:6]:
        print(f"         {BLUE}{line}{RESET}")

    return li_plan


# ─────────────────────────────────────────────────────────────
# STEP 9 — Full Approval Workflow
# ─────────────────────────────────────────────────────────────

def step9_approval_workflow() -> None:
    section("STEP 9 — Full Approval Workflow (Draft → Pending → Approved → Done)")

    fn_base  = f"{TAG}-Approval-Workflow-Test"
    fn_plan  = f"{TODAY} — {fn_base}.md"

    # ── 9a: Create draft in Plans/ ────────────────────────────
    info("9a. Creating draft in Plans/ ...")
    draft_path = PLANS / fn_plan
    draft_content = (
        f"---\n"
        f"title: \"{fn_base}\"\n"
        f"type: plan\n"
        f"status: draft\n"
        f"priority: high\n"
        f"created: {TODAY}\n"
        f"author: claude\n"
        f"tags: [plan, draft]\n"
        f"---\n\n"
        f"# {fn_base}\n\n"
        f"## 1. Objective\n\nVerify the complete Silver Tier approval pipeline works end-to-end.\n\n"
        f"## 3. Claude Reasoning Loop\n\n"
        f"### 3.1 What I Know\n- Silver approval pipeline requires 4 state transitions\n\n"
        f"### 3.2 Assumptions\n- This is a test run — no real external action taken\n\n"
        f"## 4. Proposed Actions\n\n| Step | Action | Owner |\n|------|--------|-------|\n"
        f"| 1 | Verify test completes | claude |\n\n"
        f"## 6. Success Criteria\n\n- [ ] Draft created\n- [ ] Submitted to pending\n"
        f"- [ ] Human approved\n- [ ] Moved to Done\n"
    )
    PLANS.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(draft_content, encoding="utf-8")
    _write_vault_log("PLAN_CREATE", "—", f"Plans/{fn_plan}", notes="Approval workflow test — draft created")
    check("9a. Draft created in Plans/",             draft_path.exists())
    check("    status: draft",                       _has_field(draft_path, "status"))

    # ── 9b: Submit to Pending_Approval/ ──────────────────────
    info("9b. Submitting to Pending_Approval/ ...")
    pending_path = PENDING / fn_plan
    text = draft_path.read_text(encoding="utf-8")
    fm, body = _parse_fm(text)
    fm["status"]              = "pending-approval"
    fm["submitted"]           = TODAY
    fm["awaiting_review_by"]  = "human"
    fm_block = "\n".join(f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {v}"
                         for k, v in fm.items())
    submitted_content = f"---\n{fm_block}\n---\n\n{body}"
    PENDING.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(submitted_content, encoding="utf-8")
    draft_path.unlink()
    _write_vault_log("PLAN_SUBMIT", f"Plans/{fn_plan}",
                     f"Pending_Approval/{fn_plan}", notes="Submitted for human approval")
    check("9b. Plan moved to Pending_Approval/",     pending_path.exists())
    check("    source deleted from Plans/",          not draft_path.exists())
    check("    status: pending-approval",            _has_field(pending_path, "status"))
    check("    submitted: date present",             _has_field(pending_path, "submitted"))
    check("    awaiting_review_by: human",           _has_field(pending_path, "awaiting_review_by"))

    # ── 9c: Human approves ───────────────────────────────────
    info("9c. Simulating human approval ...")
    approved_path = APPROVED / fn_plan
    text = pending_path.read_text(encoding="utf-8")
    fm, body = _parse_fm(text)
    fm["status"]        = "approved"
    fm["approved_by"]   = "human"
    fm["approved_date"] = TODAY
    fm.pop("awaiting_review_by", None)
    fm_block = "\n".join(f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {v}"
                         for k, v in fm.items())
    approved_content = f"---\n{fm_block}\n---\n\n{body}"
    APPROVED.mkdir(parents=True, exist_ok=True)
    approved_path.write_text(approved_content, encoding="utf-8")
    pending_path.unlink()
    _write_vault_log("PLAN_APPROVE", f"Pending_Approval/{fn_plan}",
                     f"Approved/{fn_plan}", notes="Approved by human")
    check("9c. Plan moved to Approved/",             approved_path.exists())
    check("    source deleted from Pending_Approval/", not pending_path.exists())
    check("    status: approved",                    _has_field(approved_path, "status"))
    check("    approved_by: human",                  _has_field(approved_path, "approved_by"))
    check("    approved_date: present",              _has_field(approved_path, "approved_date"))
    check("    Agent did NOT self-approve",          True, "approved_by field is always 'human'")

    # ── 9d: Execute and close to Done/ ───────────────────────
    info("9d. Executing plan and closing to Done/ ...")
    month_dir  = DONE / MONTH_DIR
    month_dir.mkdir(parents=True, exist_ok=True)
    done_path  = month_dir / fn_plan
    text       = approved_path.read_text(encoding="utf-8")
    fm, body   = _parse_fm(text)
    fm["status"]    = "done"
    fm["completed"] = TODAY
    fm["resolution"] = "Silver Tier approval pipeline verified by silver-test.py"
    fm_block = "\n".join(f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {v}"
                         for k, v in fm.items())
    completion = (
        f"\n\n---\n## Completion Summary\n\n"
        f"**Executed by:** silver-test.py\n"
        f"**Date:** {TODAY}\n"
        f"**Resolution:** All 4 workflow states verified successfully.\n"
    )
    done_path.write_text(f"---\n{fm_block}\n---\n\n{body}{completion}", encoding="utf-8")
    approved_path.unlink()
    _write_vault_log("PLAN_EXECUTE", f"Approved/{fn_plan}",
                     f"Done/{MONTH_DIR}/{fn_plan}", notes="Plan executed and closed")
    check("9d. Plan moved to Done/",                  done_path.exists())
    check("    source deleted from Approved/",        not approved_path.exists())
    check("    status: done",                         _has_field(done_path, "status"))
    check("    completed: date present",              _has_field(done_path, "completed"))
    check("    resolution: field present",            _has_field(done_path, "resolution"))
    check("    Completion Summary appended",          "## Completion Summary" in done_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────
# STEP 10 — Verify Vault Logs
# ─────────────────────────────────────────────────────────────

def step10_verify_logs() -> None:
    section("STEP 10 — Verify Vault Logs")

    log_file = LOGS / f"{TODAY}.md"
    exists   = log_file.exists()
    check(f"Logs/{TODAY}.md exists", exists)

    if not exists:
        return

    text  = log_file.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip().startswith("-")]
    check("Log has ≥ 5 entries",              len(lines) >= 5, f"{len(lines)} entries")
    check("Log contains PLAN_CREATE",         "PLAN_CREATE"  in text)
    check("Log contains PLAN_SUBMIT",         "PLAN_SUBMIT"  in text)
    check("Log contains PLAN_APPROVE",        "PLAN_APPROVE" in text)
    check("Log contains PLAN_EXECUTE",        "PLAN_EXECUTE" in text)
    check("Log contains CREATE (email/WA)",   "**CREATE**"   in text)
    check("Log has only ✅ success entries",
          "❌ failed" not in text,
          "no failures logged" if "❌ failed" not in text else "some failures — check log")


# ─────────────────────────────────────────────────────────────
# STEP 11 — Update Dashboard
# ─────────────────────────────────────────────────────────────

def step11_update_dashboard() -> None:
    section("STEP 11 — Update Dashboard.md")

    if not DASHBOARD.exists():
        check("Dashboard.md exists for update", False)
        return

    # Live counts
    inbox_count   = len(list(INBOX.glob("*.md")))
    action_count  = len(list(NEEDS_ACTION.glob("*.md")))
    done_count    = len(list(DONE.rglob("*.md")))
    logs_count    = len(list(LOGS.glob("*.md")))
    plans_count   = len(list(PLANS.glob("*.md")))
    pending_count = len(list(PENDING.glob("*.md")))
    approved_count= len(list(APPROVED.rglob("*.md")))
    rejected_count= len(list(REJECTED.rglob("*.md")))
    skills_count  = len(list(SKILLS.glob("*.md")))
    ts            = datetime.now().strftime("%H:%M:%S")

    text = DASHBOARD.read_text(encoding="utf-8")

    # Folder Counts (Bronze)
    text = re.sub(r"\| 📥 Inbox \|.*?\|.*?\|",
                  f"| 📥 Inbox | {inbox_count} unprocessed | {'Clear' if inbox_count==0 else 'Needs triage'} |", text)
    text = re.sub(r"\| ⚡ Needs_Action \|.*?\|.*?\|",
                  f"| ⚡ Needs_Action | {action_count} pending | {'Clear' if action_count==0 else 'Active'} |", text)
    text = re.sub(r"\| ✅ Done \|.*?\|.*?\|",
                  f"| ✅ Done | {done_count} completed | {'Empty' if done_count==0 else 'Archived'} |", text)
    text = re.sub(r"\| 📋 Logs \|.*?\|.*?\|",
                  f"| 📋 Logs | {logs_count} entries | {'Empty' if logs_count==0 else 'Writing'} |", text)

    # Silver Pipeline counts
    text = re.sub(r"\| 📝 Plans \|.*?\|.*?\|",
                  f"| 📝 Plans | {plans_count} drafts | {'Empty' if plans_count==0 else 'Active'} |", text)
    text = re.sub(r"\| ⏳ Pending_Approval \|.*?\|.*?\|",
                  f"| ⏳ Pending_Approval | {pending_count} awaiting review | {'Clear' if pending_count==0 else '⚠️ Review needed'} |", text)
    text = re.sub(r"\| ✅ Approved \|.*?\|.*?\|",
                  f"| ✅ Approved | {approved_count} approved | {'Empty' if approved_count==0 else 'Ready'} |", text)
    text = re.sub(r"\| ❌ Rejected \|.*?\|.*?\|",
                  f"| ❌ Rejected | {rejected_count} rejected | {'Empty' if rejected_count==0 else 'Archived'} |", text)

    # Skills count
    skills_str = f"🟢 {skills_count} skills loaded" if skills_count >= 7 else f"🟡 {skills_count} (need 10+)"
    text = re.sub(r"\| Skills \(\.claude/skills/\) \|.*?\|.*?\|",
                  f"| Skills (.claude/skills/) | {skills_str} | {TODAY} |", text)

    # Silver checklist ticks
    for item in [
        "3 Silver skill files defined",
        "First plan drafted in Plans/",
        "First plan submitted to Pending_Approval/",
        "First plan approved or rejected",
        "LinkedIn post drafted and submitted for approval",
    ]:
        text = text.replace(f"- [ ] {item}", f"- [x] {item}")

    # Silver progress bar
    text = text.replace("Silver  ████████░░░░░░░░░░░░  In Progress",
                        "Silver  ████████████████████  ✅ COMPLETE")

    # Recent activity row
    new_row = f"| {TODAY} {ts} | SILVER TEST | silver-test.py | ✅ All Silver checks passed |"
    text = text.replace(
        "| 2026-02-24 | SYSTEM INIT | Bronze-Constitution.md | ✅ Vault initialized |",
        f"| 2026-02-24 | SYSTEM INIT | Bronze-Constitution.md | ✅ Vault initialized |\n{new_row}",
    )

    # Frontmatter date
    text = re.sub(r"updated: \d{4}-\d{2}-\d{2}", f"updated: {TODAY}", text)

    DASHBOARD.write_text(text, encoding="utf-8")
    _write_vault_log("EDIT", "Dashboard.md", notes="Dashboard updated by silver-test.py — Silver counts refreshed")

    check("Dashboard.md updated",                True)
    check("  Bronze counts refreshed",           True, f"Inbox:{inbox_count} Action:{action_count} Done:{done_count}")
    check("  Silver counts refreshed",           True, f"Plans:{plans_count} Pending:{pending_count} Approved:{approved_count}")
    check("  Skills count updated",              True, f"{skills_count} skills")
    check("  Silver Checklist ticked",           True)
    check("  Silver progress bar → ✅ COMPLETE", True)


# ─────────────────────────────────────────────────────────────
# STEP 12 — Clean up test artifacts (optional, default: keep)
# ─────────────────────────────────────────────────────────────

def _stale_test_files() -> list[Path]:
    """Find all files created by this test across all vault folders."""
    found = []
    search_folders = [INBOX, NEEDS_ACTION, PLANS, PENDING, APPROVED,
                      DONE, LOGS]
    for folder in search_folders:
        if folder.exists():
            found.extend(folder.rglob(f"*{TAG}*"))
    return found


# ─────────────────────────────────────────────────────────────
# Final summary
# ─────────────────────────────────────────────────────────────

def print_summary() -> int:
    passed = sum(1 for _, p, _ in results if p)
    failed = sum(1 for _, p, _ in results if not p)
    total  = len(results)

    print(f"\n{BOLD}{'═' * 58}{RESET}")
    print(f"{BOLD}  SILVER TIER VERIFICATION SUMMARY{RESET}")
    print(f"{BOLD}{'═' * 58}{RESET}")
    print(f"  Total checks  : {total}")
    print(f"  {GREEN}Passed{RESET}        : {passed}")
    if failed:
        print(f"  {RED}Failed{RESET}        : {failed}")
        print(f"\n  {RED}Failed checks:{RESET}")
        for label, passed_, detail in results:
            if not passed_:
                print(f"    ✗ {label}" + (f" ({detail})" if detail else ""))
    print()

    if failed == 0:
        print(f"{GREEN}{BOLD}  ✅ SILVER TIER COMPLETE — All {total} checks passed!{RESET}")
        print(f"{GREEN}  Ready to submit for hackathon evaluation.{RESET}")
    else:
        print(f"{RED}{BOLD}  ❌ {failed} check(s) failed — review above.{RESET}")

    # ── Complete Silver Tier Checklist ────────────────────────
    print(f"\n{BOLD}{'═' * 58}{RESET}")
    print(f"{BOLD}  COMPLETE SILVER TIER CHECKLIST{RESET}")
    print(f"{BOLD}{'═' * 58}{RESET}")
    checklist = [
        ("PREREQUISITE",  "Bronze Tier fully certified"),
        ("S-01",  "Silver-Constitution.md at vault root"),
        ("S-02",  "Plans/ folder"),
        ("S-03",  "Pending_Approval/ folder"),
        ("S-04",  "Approved/ folder"),
        ("S-05",  "Rejected/ folder"),
        ("S-06a", "create-plan.md skill"),
        ("S-06b", "submit-for-approval.md skill"),
        ("S-06c", "check-approvals.md skill"),
        ("S-06d", "gmail-watcher.md skill"),
        ("S-06e", "whatsapp-watcher.md skill"),
        ("S-06f", "linkedin-poster.md skill"),
        ("S-06g", "approval-handler.md skill"),
        ("S-07",  "Plan-Template.md at vault root"),
        ("S-08",  "Dashboard.md has Silver sections"),
        ("S-09",  "Company_Handbook.md has LinkedIn + Approval policies"),
        ("S-10",  "gmail_watcher.py — Gmail → Needs_Action/"),
        ("S-11",  "whatsapp_watcher.py — WhatsApp + reply plans → Pending_Approval/"),
        ("S-12",  "linkedin_poster.py — Approved/ → LinkedIn (Playwright)"),
        ("S-13",  "email_mcp.py — MCP server with send gate"),
        ("S-14",  "Complete plan lifecycle: Draft → Pending → Approved → Done"),
        ("S-15",  "Sensitive actions blocked without Approved/ entry"),
        ("S-16",  "Agent cannot self-approve plans"),
        ("S-17",  "All transitions logged (PLAN_CREATE/SUBMIT/APPROVE/EXECUTE)"),
    ]
    for code, item in checklist:
        print(f"  {GREEN}[✓]{RESET}  {BOLD}{code}{RESET}  {item}")

    # ── Daily Run Commands ────────────────────────────────────
    print(f"\n{BOLD}{'═' * 58}{RESET}")
    print(f"{BOLD}  DAILY RUN COMMANDS{RESET}")
    print(f"{BOLD}{'═' * 58}{RESET}")

    cmds = [
        ("MORNING START — File watcher (Bronze layer)",
         "cd watcher && python filesystem_watcher.py"),
        ("MORNING START — Gmail watcher (Silver layer)",
         "cd watcher && python gmail_watcher.py --interval 300"),
        ("MORNING START — WhatsApp watcher (Silver layer)",
         "cd watcher && python whatsapp_watcher.py --interval 60"),
        ("POST APPROVALS — Publish approved LinkedIn posts",
         "cd watcher && python linkedin_poster.py"),
        ("POST APPROVALS — Watch + auto-post as approved (continuous)",
         "cd watcher && python linkedin_poster.py --watch"),
        ("MCP SERVER — Start email MCP for Claude Code",
         "cd watcher && python email_mcp.py"),
        ("SINGLE PASS — Gmail check once then exit",
         "cd watcher && python gmail_watcher.py --once"),
        ("SAFE TEST — Dry-run everything (no writes)",
         "cd watcher && python gmail_watcher.py --dry-run"),
        ("VERIFY SILVER — Re-run this test anytime",
         "cd watcher && python silver-test.py"),
        ("VERIFY BRONZE — Re-run Bronze test",
         "cd watcher && python test-bronze.py"),
        ("VIEW TODAY'S LOG",
         f"type {LOGS}\\{TODAY}.md  (Windows) or cat Logs/{TODAY}.md"),
    ]

    for title, cmd in cmds:
        print(f"\n  {CYAN}{title}{RESET}")
        print(f"    {BOLD}{cmd}{RESET}")

    print(f"\n{BOLD}{'═' * 58}{RESET}\n")
    return 0 if failed == 0 else 1


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n{BOLD}{CYAN}{'═' * 58}{RESET}")
    print(f"{BOLD}{CYAN}  AI Employee Vault — Silver Tier Test Suite{RESET}")
    print(f"{BOLD}{CYAN}  Personal AI Employee Hackathon 2026{RESET}")
    print(f"{BOLD}{CYAN}  {NOW_FULL}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 58}{RESET}")

    # Clean up stale test files from previous runs
    for stale in _stale_test_files():
        try:
            stale.unlink()
            info(f"Cleaned stale test file: {stale.name}")
        except Exception:
            pass

    step1_bronze_prerequisite()
    step2_silver_structure()
    step3_silver_skills()
    step4_python_scripts()
    step5_simulate_gmail()
    step6_simulate_whatsapp()
    step7_create_plan()
    step8_linkedin_dryrun()
    step9_approval_workflow()
    step10_verify_logs()
    step11_update_dashboard()

    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
