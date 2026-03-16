"""
weekly_audit.py
---------------
Gold Tier — Weekly Audit + CEO Briefing Generator.

Runs the full cross-domain weekly audit entirely from vault data.
No external API calls — all data comes from files in the vault.

Produces:
  - Accounting/YYYY-WW — Accounting-Audit.md  (financial summary)
  - Briefings/YYYY-WW — CEO-Briefing.md       (7-section executive briefing)
  - Dashboard.md update                        (link to new briefing)

Run:
    python weekly_audit.py                     # run for current week
    python weekly_audit.py --week 2026-08      # run for specific ISO week
    python weekly_audit.py --dry-run           # print report, write no files
    python weekly_audit.py --domain business   # filter to one domain
    python weekly_audit.py --tasks             # audit tasks only
    python weekly_audit.py --social            # audit social only
    python weekly_audit.py --accounting        # audit accounting only

Trigger:
    Schedule: every Monday at session start
    Manual:   python weekly_audit.py
"""

import os
import re
import sys
import argparse
import yaml
from datetime import datetime, timedelta
from pathlib import Path

from audit_logger import AuditLogger

# ── Config ────────────────────────────────────────────────────

VAULT_PATH = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
DRY_RUN    = os.getenv("DRY_RUN", "false").lower() == "true"

LOGS_PATH            = VAULT_PATH / os.getenv("LOGS_FOLDER",          "Logs")
ACCOUNTING_PATH      = VAULT_PATH / "Accounting"
BRIEFINGS_PATH       = VAULT_PATH / "Briefings"
SOCIAL_SUMMARIES_PATH = VAULT_PATH / "Social_Summaries"
DONE_PATH            = VAULT_PATH / "Done"
NEEDS_ACTION_PATH    = VAULT_PATH / os.getenv("NEEDS_ACTION_FOLDER",  "Needs_Action")
APPROVED_PATH        = VAULT_PATH / "Approved"
REJECTED_PATH        = VAULT_PATH / "Rejected"
PENDING_PATH         = VAULT_PATH / "Pending_Approval"
DASHBOARD_PATH       = VAULT_PATH / "Dashboard.md"


# ── Helpers ───────────────────────────────────────────────────

def parse_frontmatter(text: str) -> "tuple[dict, str]":
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, parts[2].strip()


def iso_week_range(year: int, week: int) -> "tuple[datetime, datetime]":
    """Return (monday, sunday) for the given ISO year+week."""
    jan4 = datetime(year, 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    monday = week1_monday + timedelta(weeks=week - 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def files_in_range(folder: Path, start: datetime, end: datetime) -> "list[Path]":
    """Return .md files in folder modified/created within [start, end]."""
    result = []
    if not folder.exists():
        return result
    for f in folder.rglob("*.md"):
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            date_str = fm.get("created") or fm.get("date") or fm.get("completed")
            if date_str:
                try:
                    d = datetime.strptime(str(date_str), "%Y-%m-%d")
                    if start <= d <= end:
                        result.append(f)
                    continue
                except ValueError:
                    pass
            # Fallback: file modification time
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if start <= mtime <= end:
                result.append(f)
        except Exception:
            result.append(f)   # include if we can't determine date
    return result


# ── Audit Sections ────────────────────────────────────────────

def audit_tasks(start: datetime, end: datetime) -> dict:
    """Count and list tasks from Done/ and Needs_Action/."""
    done_files = []
    for month_dir in DONE_PATH.glob("*") if DONE_PATH.exists() else []:
        if month_dir.is_dir():
            done_files.extend(files_in_range(month_dir, start, end))
    done_files.extend(files_in_range(DONE_PATH, start, end))

    open_tasks = []
    blocked_tasks = []
    if NEEDS_ACTION_PATH.exists():
        for f in NEEDS_ACTION_PATH.glob("*.md"):
            try:
                fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
                if fm.get("type") != "escalation":
                    open_tasks.append({"title": fm.get("title", f.stem), "priority": fm.get("priority"), "due": fm.get("due"), "status": fm.get("status")})
                    if fm.get("status") == "blocked":
                        blocked_tasks.append(fm.get("title", f.stem))
            except Exception:
                open_tasks.append({"title": f.stem})

    done_titles = []
    for f in done_files:
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            done_titles.append(fm.get("title", f.stem))
        except Exception:
            done_titles.append(f.stem)

    return {
        "completed": len(done_files),
        "open": len(open_tasks),
        "blocked": len(blocked_tasks),
        "done_titles": done_titles[:20],
        "open_items": open_tasks,
        "blocked_titles": blocked_tasks,
    }


def audit_social(start: datetime, end: datetime, week_str: str) -> dict:
    """Count social posts from Social_Summaries/ or Logs/."""
    platforms = {"facebook": 0, "instagram": 0, "twitter": 0, "linkedin": 0}
    failures = []
    source_file = None

    # Primary: Social_Summaries/YYYY-WW — Social-Summary.md
    summary_file = SOCIAL_SUMMARIES_PATH / f"{week_str} — Social-Summary.md"
    if summary_file.exists():
        source_file = str(summary_file.relative_to(VAULT_PATH))
        try:
            fm, body = parse_frontmatter(summary_file.read_text(encoding="utf-8"))
            for platform in platforms:
                count_match = re.search(rf"{platform}[:\s]+(\d+)", body, re.IGNORECASE)
                if count_match:
                    platforms[platform] = int(count_match.group(1))
        except Exception:
            pass
    else:
        # Fallback: scan Logs/ for SOCIAL_POST entries
        source_file = "Logs/ (SOCIAL_POST entries)"
        if LOGS_PATH.exists():
            for log_file in LOGS_PATH.glob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if not (start <= mtime <= end + timedelta(days=1)):
                        continue
                    content = log_file.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if "SOCIAL_POST" in line:
                            for platform in platforms:
                                if platform in line.lower():
                                    platforms[platform] += 1
                        if "ERROR" in line and any(p in line.lower() for p in platforms):
                            failures.append(line.strip()[:100])
                except Exception:
                    continue

    total = sum(platforms.values())
    return {
        "total": total,
        "platforms": platforms,
        "failures": failures[:5],
        "source": source_file,
    }


def audit_accounting(start: datetime, end: datetime) -> dict:
    """Read Accounting/ files for the week. Sum income and expenses."""
    if not ACCOUNTING_PATH.exists():
        return {"income": None, "expenses": None, "outstanding": [], "files": []}

    income = 0.0
    expenses = 0.0
    outstanding = []
    files_read = []

    for f in ACCOUNTING_PATH.glob("*.md"):
        try:
            fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
            period = fm.get("period", "")
            # Check if this file covers our week range
            date_str = fm.get("created") or fm.get("date")
            if date_str:
                try:
                    d = datetime.strptime(str(date_str), "%Y-%m-%d")
                    if not (start - timedelta(days=1) <= d <= end + timedelta(days=1)):
                        continue
                except ValueError:
                    pass

            files_read.append(f.name)
            # Parse income/expense numbers from body
            income_match  = re.search(r"income[:\s]+[\$£€]?([\d,.]+)", body, re.IGNORECASE)
            expense_match = re.search(r"expense[s]?[:\s]+[\$£€]?([\d,.]+)", body, re.IGNORECASE)
            if income_match:
                income  += float(income_match.group(1).replace(",", ""))
            if expense_match:
                expenses += float(expense_match.group(1).replace(",", ""))

            # Outstanding items: lines with "outstanding", "unpaid", "overdue"
            for line in body.splitlines():
                if any(k in line.lower() for k in ["outstanding", "unpaid", "overdue"]):
                    outstanding.append(line.strip()[:80])

        except Exception:
            continue

    return {
        "income":      income if files_read else None,
        "expenses":    expenses if files_read else None,
        "outstanding": outstanding[:10],
        "files":       files_read,
    }


def audit_approvals() -> dict:
    """Count approved/rejected/pending plans and flag old pending items."""
    approved  = len(list(APPROVED_PATH.glob("*.md")))  if APPROVED_PATH.exists()  else 0
    rejected  = len(list(REJECTED_PATH.glob("*.md")))  if REJECTED_PATH.exists()  else 0

    pending_items = []
    long_pending  = []
    if PENDING_PATH.exists():
        for f in PENDING_PATH.glob("*.md"):
            try:
                fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
                created_str = fm.get("created") or fm.get("submitted")
                age_hours = 0
                if created_str:
                    try:
                        created = datetime.strptime(str(created_str), "%Y-%m-%d")
                        age_hours = int((datetime.now() - created).total_seconds() / 3600)
                    except ValueError:
                        pass
                item = {"title": fm.get("title", f.stem), "age_hours": age_hours}
                pending_items.append(item)
                if age_hours >= 48:
                    long_pending.append(item)
            except Exception:
                pending_items.append({"title": f.stem, "age_hours": 0})

    return {
        "approved":     approved,
        "rejected":     rejected,
        "pending":      len(pending_items),
        "pending_items": pending_items,
        "long_pending": long_pending,
    }


def audit_errors(start: datetime, end: datetime) -> dict:
    """Scan Logs/ for ERROR and ESCALATE entries this week."""
    errors_by_skill: dict = {}
    total_errors = 0

    if not LOGS_PATH.exists():
        return {"total": 0, "by_skill": {}, "loop_aborts": 0}

    loop_aborts = 0
    for log_file in sorted(LOGS_PATH.glob("*.md")):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if not (start - timedelta(days=1) <= mtime <= end + timedelta(days=1)):
                continue
            for line in log_file.read_text(encoding="utf-8").splitlines():
                if "**ERROR**" in line or "**ESCALATE**" in line:
                    total_errors += 1
                    # Try to extract skill name
                    skill_match = re.search(r"skill[/:](\S+)", line, re.IGNORECASE)
                    skill = skill_match.group(1).rstrip("|") if skill_match else "unknown"
                    errors_by_skill[skill] = errors_by_skill.get(skill, 0) + 1
                if "**LOOP_ABORT**" in line:
                    loop_aborts += 1
        except Exception:
            continue

    return {"total": total_errors, "by_skill": errors_by_skill, "loop_aborts": loop_aborts}


def audit_upcoming_deadlines() -> list:
    """Return tasks due within the next 7 days, sorted by due date."""
    upcoming = []
    now = datetime.now()
    window = now + timedelta(days=7)

    if not NEEDS_ACTION_PATH.exists():
        return upcoming

    for f in NEEDS_ACTION_PATH.glob("*.md"):
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            due_str = fm.get("due")
            if due_str:
                try:
                    due = datetime.strptime(str(due_str), "%Y-%m-%d")
                    if now <= due <= window:
                        upcoming.append({
                            "title": fm.get("title", f.stem),
                            "due":   str(due_str),
                            "priority": fm.get("priority", "—"),
                        })
                except ValueError:
                    pass
        except Exception:
            continue

    upcoming.sort(key=lambda x: x["due"])
    return upcoming[:15]


# ── Report Builders ───────────────────────────────────────────

def build_ceo_briefing(
    week_str: str,
    year: int,
    week_num: int,
    start: datetime,
    end: datetime,
    tasks: dict,
    social: dict,
    accounting: dict,
    approvals: dict,
    errors: dict,
    deadlines: list,
) -> str:
    now       = datetime.now().strftime("%Y-%m-%d %H:%M")
    period    = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    total_posts = social["total"]

    # Section 1 — Executive Summary
    summary_bullets = [
        f"- {tasks['completed']} tasks completed, {tasks['open']} open, {tasks['blocked']} blocked.",
        f"- {total_posts} social media posts published across {sum(1 for v in social['platforms'].values() if v > 0)} platforms.",
    ]
    if errors["total"] > 0:
        summary_bullets.append(f"- {errors['total']} errors logged this week ({errors['loop_aborts']} loop aborts).")
    if approvals["long_pending"]:
        summary_bullets.append(f"- {len(approvals['long_pending'])} plan(s) waiting >48h in Pending_Approval/.")
    if not accounting["files"]:
        summary_bullets.append("- No accounting records this week.")

    # Section 2 — Tasks
    done_list = "\n".join(f"  - {t}" for t in (tasks["done_titles"] or ["No completed tasks."])) or "  - No completed tasks."
    blocked_list = "\n".join(f"  - {t}" for t in (tasks["blocked_titles"] or [])) or "  - None"

    # Section 3 — Social
    plat = social["platforms"]
    social_lines = (
        f"- Facebook: {plat.get('facebook', 0)} posts | "
        f"Instagram: {plat.get('instagram', 0)} posts | "
        f"Twitter: {plat.get('twitter', 0)} posts | "
        f"LinkedIn: {plat.get('linkedin', 0)} posts"
    )
    social_failures = "\n".join(f"  - {e}" for e in (social["failures"] or [])) or "  - None"
    social_source = social.get("source") or "No data"

    # Section 4 — Accounting
    if accounting["files"]:
        income_str   = f"${accounting['income']:.2f}"   if accounting["income"]   is not None else "No records"
        expense_str  = f"${accounting['expenses']:.2f}" if accounting["expenses"] is not None else "No records"
        outstanding  = "\n".join(f"  - {o}" for o in (accounting["outstanding"] or [])) or "  - None"
    else:
        income_str  = "No records"
        expense_str = "No records"
        outstanding = "  - None"

    # Section 5 — Approvals
    pending_list = "\n".join(
        f"  - {i['title']} (age: {i['age_hours']}h{'  ⚠️ >48h' if i['age_hours'] >= 48 else ''})"
        for i in (approvals["pending_items"] or [])
    ) or "  - None"
    blocked_tasks_section = "\n".join(
        f"  - {t}" for t in (tasks["blocked_titles"] or [])
    ) or "  - None"

    # Section 6 — Deadlines
    deadline_list = "\n".join(
        f"  - {d['title']} — due: {d['due']} (priority: {d['priority']})"
        for d in (deadlines or [])
    ) or "  - No upcoming deadlines."

    # Section 7 — Recommendations
    recommendations = []
    if errors["total"] > 3:
        top_skill = max(errors["by_skill"], key=errors["by_skill"].get) if errors["by_skill"] else "unknown"
        recommendations.append(f"- {errors['total']} errors this week — review `{top_skill}` logs and consider re-authenticating the browser session.")
    if approvals["long_pending"]:
        recommendations.append(f"- {len(approvals['long_pending'])} plan(s) waiting >48h — review and approve/reject them in Pending_Approval/.")
    if tasks["blocked"]:
        recommendations.append(f"- {tasks['blocked']} blocked task(s) need attention — check Needs_Action/ for blocked items.")
    if not recommendations:
        recommendations.append("- No critical actions needed. Vault is operating normally.")

    rec_list = "\n".join(recommendations)

    # Frontmatter
    frontmatter = (
        f"---\n"
        f"title: \"CEO Briefing — Week {week_num:02d}, {year}\"\n"
        f"type: ceo-briefing\n"
        f"week: {week_num}\n"
        f"year: {year}\n"
        f"period: \"{period}\"\n"
        f"status: pending-review\n"
        f"generated_by: claude\n"
        f"generated_at: \"{now}\"\n"
        f"tasks_completed: {tasks['completed']}\n"
        f"social_posts: {total_posts}\n"
        f"errors_this_week: {errors['total']}\n"
        f"tags: [briefing, ceo, weekly, gold]\n"
        f"---\n\n"
    )

    body = f"""# CEO Briefing — Week {week_num:02d}, {year}

**Period:** {period}
**Generated:** {now}
**Status:** Pending Review

---

## 1. Executive Summary

{chr(10).join(summary_bullets)}

---

## 2. Tasks Completed

- **Total:** {tasks['completed']} completed, {tasks['open']} open, {tasks['blocked']} blocked

**Completed this week:**
{done_list}

**Blocked tasks:**
{blocked_list}

---

## 3. Social Media Activity

{social_lines}

**Failures/Escalations:**
{social_failures}

**Source:** `{social_source}`

---

## 4. Accounting / Financial Summary

- **Income this week:** {income_str}
- **Expenses this week:** {expense_str}
- **Outstanding items:**
{outstanding}

**Source:** `Accounting/` files

---

## 5. Pending Approvals & Blockers

**Plans in Pending_Approval/:**
{pending_list}

**Blocked tasks:**
{blocked_tasks_section}

> ⚠️ Plans waiting >48h require immediate human review per Silver-Constitution.md.

---

## 6. Upcoming Deadlines

{deadline_list}

---

## 7. Agent Recommendations

{rec_list}

---

*Generated by `weekly_audit.py` | AI_Employee_Vault Gold Tier | Hackathon 2026*
"""
    return frontmatter + body


def build_accounting_audit(
    week_str: str, year: int, week_num: int,
    start: datetime, end: datetime, accounting: dict,
) -> str:
    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    period = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"

    income_str  = f"${accounting['income']:.2f}"   if accounting["income"]   is not None else "No records"
    expense_str = f"${accounting['expenses']:.2f}" if accounting["expenses"] is not None else "No records"

    net = None
    if accounting["income"] is not None and accounting["expenses"] is not None:
        net = accounting["income"] - accounting["expenses"]
    net_str = f"${net:.2f}" if net is not None else "N/A"

    outstanding = "\n".join(f"- {o}" for o in (accounting["outstanding"] or [])) or "- None"
    sources     = ", ".join(accounting["files"]) if accounting["files"] else "No files found"

    frontmatter = (
        f"---\n"
        f"title: \"Accounting Audit — Week {week_num:02d}, {year}\"\n"
        f"type: accounting-report\n"
        f"period: \"{period}\"\n"
        f"week: {week_num}\n"
        f"year: {year}\n"
        f"status: draft\n"
        f"domain: all\n"
        f"generated_by: claude\n"
        f"generated_at: \"{now}\"\n"
        f"tags: [accounting, audit, weekly, gold]\n"
        f"---\n\n"
    )

    body = f"""# Accounting Audit — Week {week_num:02d}, {year}

**Period:** {period}
**Generated:** {now}

| Metric | Amount |
|--------|--------|
| Income this week | {income_str} |
| Expenses this week | {expense_str} |
| Net | {net_str} |

## Outstanding Items

{outstanding}

## Source Files

{sources}

---

*Generated by `weekly_audit.py` | AI_Employee_Vault Gold Tier*
"""
    return frontmatter + body


# ── Dashboard Update ──────────────────────────────────────────

def update_dashboard(briefing_rel_path: str) -> None:
    """Prepend briefing link under ## Latest Briefing in Dashboard.md."""
    if not DASHBOARD_PATH.exists():
        return
    try:
        content = DASHBOARD_PATH.read_text(encoding="utf-8")
        now     = datetime.now().strftime("%Y-%m-%d")
        link    = f"- [[{briefing_rel_path}]] — generated {now}\n"

        if "## Latest Briefing" in content:
            content = content.replace(
                "## Latest Briefing\n",
                f"## Latest Briefing\n\n{link}",
                1,
            )
        else:
            content += f"\n## Latest Briefing\n\n{link}\n"

        if not DRY_RUN:
            DASHBOARD_PATH.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Could not update Dashboard.md: {e}")


# ── Main ──────────────────────────────────────────────────────

def run_audit(
    week_override: "str | None" = None,
    domain: str = "all",
    tasks_only: bool = False,
    social_only: bool = False,
    accounting_only: bool = False,
) -> None:
    audit = AuditLogger(VAULT_PATH)

    # Determine week
    now = datetime.now()
    if week_override:
        # Format: YYYY-WW
        try:
            year, week_num = map(int, week_override.split("-"))
        except ValueError:
            print(f"Invalid week format: {week_override} (expected YYYY-WW)")
            sys.exit(1)
    else:
        year     = now.isocalendar()[0]
        week_num = now.isocalendar()[1]

    start, end = iso_week_range(year, week_num)
    week_str   = f"{year}-{week_num:02d}"

    print()
    print("=" * 60)
    print(f"  AI Employee Vault — Weekly Audit")
    print(f"  Gold Tier | Week {week_num:02d}, {year}")
    print(f"  Period: {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}")
    print(f"  Domain: {domain}")
    print(f"  Mode:   {'DRY-RUN' if DRY_RUN else 'LIVE'}")
    print("=" * 60)
    print()

    audit.log_action(
        "AUDIT_RUN", "weekly-audit", "Logs/",
        notes=f"Week {week_str} audit started — domain: {domain}",
    )

    # Ensure output folders exist
    if not DRY_RUN:
        ACCOUNTING_PATH.mkdir(parents=True, exist_ok=True)
        BRIEFINGS_PATH.mkdir(parents=True, exist_ok=True)

    # Run audit sections
    tasks_data      = audit_tasks(start, end)          if not social_only and not accounting_only  else {}
    social_data     = audit_social(start, end, week_str) if not tasks_only  and not accounting_only else {}
    accounting_data = audit_accounting(start, end)      if not tasks_only  and not social_only      else {}
    approvals_data  = audit_approvals()                 if not tasks_only  and not social_only and not accounting_only else {}
    errors_data     = audit_errors(start, end)          if not tasks_only  and not social_only and not accounting_only else {}
    deadlines       = audit_upcoming_deadlines()        if not social_only and not accounting_only  else []

    # Defaults if sections skipped
    tasks_data      = tasks_data      or {"completed": 0, "open": 0, "blocked": 0, "done_titles": [], "open_items": [], "blocked_titles": []}
    social_data     = social_data     or {"total": 0, "platforms": {p: 0 for p in ["facebook","instagram","twitter","linkedin"]}, "failures": [], "source": None}
    accounting_data = accounting_data or {"income": None, "expenses": None, "outstanding": [], "files": []}
    approvals_data  = approvals_data  or {"approved": 0, "rejected": 0, "pending": 0, "pending_items": [], "long_pending": []}
    errors_data     = errors_data     or {"total": 0, "by_skill": {}, "loop_aborts": 0}

    print(f"Tasks   : {tasks_data['completed']} completed, {tasks_data['open']} open")
    print(f"Social  : {social_data['total']} posts")
    print(f"Errors  : {errors_data['total']}")
    print(f"Pending : {approvals_data['pending']} plans waiting")
    print()

    # ── Write Accounting Audit ────────────────────────────────
    if not tasks_only and not social_only:
        accounting_content   = build_accounting_audit(
            week_str, year, week_num, start, end, accounting_data
        )
        accounting_filename  = f"{week_str} — Accounting-Audit.md"
        accounting_dest      = ACCOUNTING_PATH / accounting_filename

        if DRY_RUN:
            print("[DRY-RUN] Accounting Audit (preview):")
            print(accounting_content[:400])
            print("...")
        else:
            accounting_dest.write_text(accounting_content, encoding="utf-8")
            print(f"Written: Accounting/{accounting_filename}")

        audit.log_action(
            "AUDIT_RUN", "weekly-audit",
            "Logs/", f"Accounting/{accounting_filename}",
            notes=f"week: {week_num} | tasks: {tasks_data['completed']} | errors: {errors_data['total']}",
        )

    # ── Write CEO Briefing ────────────────────────────────────
    briefing_content  = build_ceo_briefing(
        week_str, year, week_num, start, end,
        tasks_data, social_data, accounting_data,
        approvals_data, errors_data, deadlines,
    )
    briefing_filename = f"{week_str} — CEO-Briefing.md"
    briefing_dest     = BRIEFINGS_PATH / briefing_filename
    briefing_rel      = f"Briefings/{briefing_filename}"

    # Add -r2 suffix if file already exists (never overwrite)
    if not DRY_RUN and briefing_dest.exists():
        r = 2
        while briefing_dest.with_stem(f"{briefing_dest.stem}-r{r}").exists():
            r += 1
        briefing_filename = f"{week_str} — CEO-Briefing-r{r}.md"
        briefing_dest     = BRIEFINGS_PATH / briefing_filename
        briefing_rel      = f"Briefings/{briefing_filename}"

    if DRY_RUN:
        print("[DRY-RUN] CEO Briefing (preview):")
        print(briefing_content[:600])
        print("...")
    else:
        briefing_dest.write_text(briefing_content, encoding="utf-8")
        print(f"Written: {briefing_rel}")
        update_dashboard(briefing_rel)

    audit.log_action(
        "BRIEFING_GEN", "weekly-audit",
        f"Accounting/{week_str} — Accounting-Audit.md",
        briefing_rel, "success",
        notes=f"sections: 7 | status: pending-review | week: {week_str}",
    )

    print()
    print("✅ Weekly audit complete.")
    print(f"   Briefing: {briefing_rel}")
    print()


# ── Entry Point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Weekly Audit")
    p.add_argument("--week",       metavar="YYYY-WW", help="ISO week to audit (default: current)")
    p.add_argument("--domain",     default="all",     help="personal | business | all")
    p.add_argument("--dry-run",    action="store_true")
    p.add_argument("--tasks",      action="store_true", help="Audit tasks only")
    p.add_argument("--social",     action="store_true", help="Audit social only")
    p.add_argument("--accounting", action="store_true", help="Audit accounting only")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        DRY_RUN = True
        os.environ["DRY_RUN"] = "true"
    run_audit(
        week_override=args.week,
        domain=args.domain,
        tasks_only=args.tasks,
        social_only=args.social,
        accounting_only=args.accounting,
    )
