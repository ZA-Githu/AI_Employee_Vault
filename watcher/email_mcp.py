"""
email_mcp.py
------------
Silver Tier — Basic MCP Server for email operations.

Exposes 5 tools to Claude via the Model Context Protocol (stdio transport):

  draft_email      — Create an email draft in Pending_Approval/
  list_pending     — List emails waiting for human approval
  send_email       — Send an email that is in Approved/ (HITL enforced)
  read_vault_note  — Read any vault .md file
  log_action       — Write a structured entry to today's vault log

SENSITIVE RULE: send_email only executes if the email plan is in Approved/
with approved_by: human. The tool refuses and returns an error otherwise.

Transport: stdio (Claude Desktop / Claude Code MCP integration)

Run (directly for testing):
    python email_mcp.py

Add to Claude Code MCP config (.claude/mcp.json):
    {
      "mcpServers": {
        "email": {
          "command": "python",
          "args": ["watcher/email_mcp.py"],
          "cwd": "<vault_root>"
        }
      }
    }

Dependencies:
    pip install mcp pyyaml
    (smtplib is Python stdlib — no install needed)
"""

import os
import re
import sys
import json
import smtplib
import asyncio
import yaml
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ── Vault paths (resolved relative to this file's parent's parent) ────
VAULT_PATH            = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
PENDING_APPROVAL_PATH = VAULT_PATH / "Pending_Approval"
APPROVED_PATH         = VAULT_PATH / "Approved"
DONE_PATH             = VAULT_PATH / "Done"
LOGS_PATH             = VAULT_PATH / "Logs"

# ── SMTP config (loaded from .env or environment) ─────────────────────
SMTP_HOST     = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER",     "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM",     SMTP_USER)

# ──────────────────────────────────────────────────────────────────────
# Vault helpers
# ──────────────────────────────────────────────────────────────────────

def _ensure_folders() -> None:
    for folder in [PENDING_APPROVAL_PATH, APPROVED_PATH, DONE_PATH, LOGS_PATH]:
        folder.mkdir(parents=True, exist_ok=True)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
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


def _sanitise_filename(text: str, max_len: int = 60) -> str:
    safe = re.sub(r'[\\/*?:"<>|\n\r]', " ", text).strip()
    safe = re.sub(r"\s+", "-", safe)
    return safe[:max_len] if safe else "email-draft"


def _write_vault_log(
    action_type: str,
    source: str,
    destination: str = "—",
    outcome: str = "success",
    notes: str = "",
) -> None:
    today     = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_file  = LOGS_PATH / f"{today}.md"
    dest_str  = f"`{destination}`" if destination != "—" else "—"
    icon      = "✅" if outcome == "success" else "❌"
    entry     = f"- `{timestamp}` | **{action_type}** | `{source}` → {dest_str} | {icon} {outcome} | {notes}\n"

    if not log_file.exists():
        LOGS_PATH.mkdir(parents=True, exist_ok=True)
        header = (
            f"---\ntitle: \"Agent Log — {today}\"\ndate: {today}\ntags: [log, agent]\n---\n\n"
            f"# Agent Log — {today}\n\n> Append-only.\n\n---\n\n"
        )
        log_file.write_text(header, encoding="utf-8")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)


# ──────────────────────────────────────────────────────────────────────
# MCP Server
# ──────────────────────────────────────────────────────────────────────

server = Server("email-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="draft_email",
            description=(
                "Create an email draft plan in Pending_Approval/. "
                "The email will NOT be sent until a human approves it "
                "and it is moved to Approved/."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "to":      {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body":    {"type": "string", "description": "Email body (plain text or markdown)"},
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "default": "medium",
                        "description": "Priority level",
                    },
                    "notes_for_reviewer": {
                        "type": "string",
                        "description": "Optional note for the human reviewer",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        ),
        types.Tool(
            name="list_pending",
            description="List all email drafts currently in Pending_Approval/ awaiting human review.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="send_email",
            description=(
                "Send an email that is in Approved/ with approved_by: human. "
                "REFUSES to send if the plan is not in Approved/ or lacks approved_by. "
                "After sending, moves the plan to Done/."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Filename of the approved email plan in Approved/",
                    },
                },
                "required": ["filename"],
            },
        ),
        types.Tool(
            name="read_vault_note",
            description="Read any .md file from the vault by relative path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from vault root (e.g. 'Approved/my-email.md')",
                    },
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="log_action",
            description="Write a structured entry to today's vault log (Logs/YYYY-MM-DD.md).",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["CREATE", "MOVE", "EDIT", "DELETE", "SKILL_RUN", "TRIAGE", "CLOSE", "ERROR"],
                    },
                    "source":      {"type": "string"},
                    "destination": {"type": "string", "default": "—"},
                    "outcome":     {"type": "string", "enum": ["success", "failed"], "default": "success"},
                    "notes":       {"type": "string"},
                },
                "required": ["action_type", "source", "notes"],
            },
        ),
    ]


# ──────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # ── draft_email ─────────────────────────────────────────────────
    if name == "draft_email":
        to       = arguments["to"].strip()
        subject  = arguments["subject"].strip()
        body     = arguments["body"].strip()
        priority = arguments.get("priority", "medium")
        reviewer_note = arguments.get("notes_for_reviewer", "")

        today    = datetime.now().strftime("%Y-%m-%d")
        safe_sub = _sanitise_filename(subject)
        filename = f"{today} — Email-{safe_sub}.md"

        content = (
            f"---\n"
            f"title: \"{subject.replace(chr(34), chr(39))}\"\n"
            f"type: email-draft\n"
            f"status: pending-approval\n"
            f"priority: {priority}\n"
            f"to: \"{to}\"\n"
            f"subject: \"{subject.replace(chr(34), chr(39))}\"\n"
            f"created: {today}\n"
            f"submitted: {today}\n"
            f"awaiting_review_by: human\n"
            f"author: claude\n"
            f"tags: [email, pending-approval, agent]\n"
            f"---\n\n"
            f"# Email Draft: {subject}\n\n"
            f"> **To:** {to}  \n"
            f"> **Priority:** {priority}  \n"
            f"> **Created:** {today}  \n\n"
            f"---\n\n"
            f"## Email Body\n\n"
            f"{body}\n\n"
            f"---\n\n"
            f"## Reviewer Notes\n\n"
            f"{reviewer_note if reviewer_note else '_No notes provided._'}\n\n"
            f"---\n\n"
            f"## Approval\n\n"
            f"- To approve: move this file to `Approved/` and add `approved_by: human`\n"
            f"- To reject: move to `Rejected/` and add `rejection_reason:`\n"
        )

        dest = PENDING_APPROVAL_PATH / filename
        if dest.exists():
            dest = PENDING_APPROVAL_PATH / f"{today} — Email-{safe_sub}-{datetime.now().strftime('%H%M%S')}.md"
            filename = dest.name

        dest.write_text(content, encoding="utf-8")
        _write_vault_log(
            "CREATE",
            f"email:draft:{to}",
            f"Pending_Approval/{filename}",
            notes=f"Email draft created — to: {to} subject: {subject}",
        )

        return [types.TextContent(
            type="text",
            text=(
                f"✅ Email draft created: `Pending_Approval/{filename}`\n\n"
                f"**To:** {to}  \n**Subject:** {subject}  \n**Priority:** {priority}\n\n"
                f"The email will not be sent until a human approves it.\n"
                f"Move the file to `Approved/` and add `approved_by: human` to approve."
            ),
        )]

    # ── list_pending ────────────────────────────────────────────────
    elif name == "list_pending":
        if not PENDING_APPROVAL_PATH.exists():
            return [types.TextContent(type="text", text="Pending_Approval/ folder does not exist.")]

        email_plans = []
        for f in sorted(PENDING_APPROVAL_PATH.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = _parse_frontmatter(text)
                if fm.get("type") == "email-draft":
                    submitted = fm.get("submitted", "unknown")
                    # Calculate age
                    try:
                        sub_dt  = datetime.strptime(str(submitted), "%Y-%m-%d")
                        age_days = (datetime.now() - sub_dt).days
                        stale    = " ⚠️ STALE" if age_days >= 2 else ""
                    except Exception:
                        age_days = 0
                        stale    = ""
                    email_plans.append(
                        f"- `{f.name}`  \n"
                        f"  To: {fm.get('to', '?')} | Subject: {fm.get('subject', '?')} | "
                        f"Submitted: {submitted} ({age_days}d ago){stale}"
                    )
            except Exception:
                continue

        if not email_plans:
            return [types.TextContent(type="text", text="No email drafts pending approval.")]

        result = "**Pending Email Approvals:**\n\n" + "\n\n".join(email_plans)
        return [types.TextContent(type="text", text=result)]

    # ── send_email ──────────────────────────────────────────────────
    elif name == "send_email":
        filename = arguments["filename"].strip()
        plan_path = APPROVED_PATH / filename

        # Gate 1: file must be in Approved/
        if not plan_path.exists():
            _write_vault_log("ERROR", f"Approved/{filename}", notes="send_email refused — not in Approved/", outcome="failed")
            return [types.TextContent(
                type="text",
                text=(
                    f"❌ **REFUSED** — `{filename}` is not in `Approved/`.\n\n"
                    "Email can only be sent after a human approves it:\n"
                    "1. Move the plan to `Approved/`\n"
                    "2. Add `approved_by: human` to the frontmatter\n"
                    "3. Then call `send_email` again."
                ),
            )]

        text = plan_path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        # Gate 2: must have approved_by
        if not fm.get("approved_by"):
            _write_vault_log("ERROR", f"Approved/{filename}", notes="send_email refused — missing approved_by", outcome="failed")
            return [types.TextContent(
                type="text",
                text=(
                    f"❌ **REFUSED** — `{filename}` is missing `approved_by:` field.\n\n"
                    "Add `approved_by: human` to the frontmatter and try again."
                ),
            )]

        # Gate 3: must be email-draft type
        if fm.get("type") != "email-draft":
            return [types.TextContent(
                type="text",
                text=f"❌ **REFUSED** — `{filename}` is not an email draft (type: {fm.get('type')}).",
            )]

        to      = fm.get("to", "")
        subject = fm.get("subject", "(no subject)")

        # Extract body content
        email_body_match = re.search(r"##\s+Email Body\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL)
        email_body = email_body_match.group(1).strip() if email_body_match else body

        if not to:
            return [types.TextContent(type="text", text="❌ No recipient address found in plan frontmatter.")]

        # Check SMTP config
        if not SMTP_USER or not SMTP_PASSWORD:
            return [types.TextContent(
                type="text",
                text=(
                    "❌ SMTP credentials not configured.\n\n"
                    "Set these in `watcher/.env`:\n"
                    "```\nSMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\n"
                    "SMTP_USER=you@gmail.com\nSMTP_PASSWORD=your-app-password\n```"
                ),
            )]

        # Send via SMTP
        try:
            msg = MIMEMultipart("alternative")
            msg["From"]    = SMTP_FROM or SMTP_USER
            msg["To"]      = to
            msg["Subject"] = subject
            msg.attach(MIMEText(email_body, "plain", "utf-8"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(SMTP_FROM or SMTP_USER, [to], msg.as_string())

        except smtplib.SMTPException as exc:
            _write_vault_log("ERROR", f"Approved/{filename}", notes=f"SMTP error: {exc}", outcome="failed")
            return [types.TextContent(type="text", text=f"❌ SMTP error: {exc}")]

        # Move plan to Done/
        today     = datetime.now().strftime("%Y-%m-%d")
        month_dir = DONE_PATH / datetime.now().strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        done_path = month_dir / filename

        completion = (
            f"\n\n---\n## Completion Summary\n\n"
            f"**Sent by:** email_mcp.py\n"
            f"**Date:** {today}\n"
            f"**To:** {to}\n"
        )
        done_path.write_text(text + completion, encoding="utf-8")
        plan_path.unlink()

        _write_vault_log(
            "SKILL_RUN",
            f"Approved/{filename}",
            f"Done/{month_dir.name}/{filename}",
            notes=f"Email sent — to: {to} subject: {subject}",
        )

        return [types.TextContent(
            type="text",
            text=(
                f"✅ Email sent successfully.\n\n"
                f"**To:** {to}  \n**Subject:** {subject}\n\n"
                f"Plan archived to `Done/{month_dir.name}/{filename}`."
            ),
        )]

    # ── read_vault_note ─────────────────────────────────────────────
    elif name == "read_vault_note":
        rel_path  = arguments["path"].strip().lstrip("/\\")
        full_path = VAULT_PATH / rel_path

        if not full_path.exists():
            return [types.TextContent(type="text", text=f"❌ File not found: {rel_path}")]
        if not full_path.is_file():
            return [types.TextContent(type="text", text=f"❌ Not a file: {rel_path}")]

        content = full_path.read_text(encoding="utf-8")
        return [types.TextContent(type="text", text=f"**{rel_path}**\n\n---\n\n{content}")]

    # ── log_action ───────────────────────────────────────────────────
    elif name == "log_action":
        _write_vault_log(
            action_type=arguments["action_type"],
            source=arguments["source"],
            destination=arguments.get("destination", "—"),
            outcome=arguments.get("outcome", "success"),
            notes=arguments.get("notes", ""),
        )
        return [types.TextContent(type="text", text="✅ Log entry written.")]

    return [types.TextContent(type="text", text=f"❌ Unknown tool: {name}")]


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    _ensure_folders()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
