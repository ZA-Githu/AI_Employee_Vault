"""
audit_logger.py
---------------
Gold Tier — Shared JSON Audit Logger + L1-L4 Error Recovery.

All Gold Tier scripts import this module to:
  - Write structured JSON entries to Logs/YYYY-MM-DD.json
  - Write Bronze-format Markdown entries to Logs/YYYY-MM-DD.md (in parallel)
  - Handle errors gracefully using the L1–L4 classification

Error Levels:
  L1 — Transient  (network, rate limit)   → retry after 30s
  L2 — Recoverable (file/format issues)   → auto-fix, then retry
  L3 — Escalatable (auth, permissions)    → escalate to human, pause skill
  L4 — Critical    (vault errors)         → halt Ralph Loop, alert dashboard

Usage:
    from audit_logger import AuditLogger

    audit = AuditLogger()
    audit.log_action("SOCIAL_POST", "facebook-poster", "Approved/post.md",
                     "Done/2026-02/post.md", "success", notes="platform: facebook")

    result = audit.handle_error(exc, retry_count=0, calling_skill="facebook-poster")
    # result = {"action": "retry", "wait_seconds": 30, "level": "L1"}
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path


class AuditLogger:
    """
    Gold Tier shared audit logger.

    Writes JSON + Markdown log entries for every action.
    Provides L1–L4 error recovery helpers to all Gold scripts.
    """

    def __init__(self, vault_path: "Path | str | None" = None):
        if vault_path is None:
            vault_path = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
        self.vault_path        = Path(vault_path).resolve()
        self.logs_path         = self.vault_path / os.getenv("LOGS_FOLDER",          "Logs")
        self.needs_action_path = self.vault_path / os.getenv("NEEDS_ACTION_FOLDER",  "Needs_Action")
        self.logger            = logging.getLogger("AuditLogger")
        self._session_id       = datetime.now().strftime("%Y-%m-%d-session-1")

    # ------------------------------------------------------------------
    # Public API — log_action
    # ------------------------------------------------------------------

    def log_action(
        self,
        action_type: str,
        skill: str,
        source: str,
        destination: "str | None" = None,
        outcome: str = "success",
        notes: str = "",
        error: "dict | None" = None,
    ) -> dict:
        """
        Write a structured JSON + Markdown audit entry.

        action_type : see Action Types in audit-logger.md
        skill       : name of calling skill / script
        source      : relative source path or resource name
        destination : relative destination path (or None)
        outcome     : "success" | "failed" | "skipped" | "escalated"
        notes       : human-readable description
        error       : {"message": ..., "level": ..., "recovery_action": ...}

        Returns the written entry dict.
        """
        entry = {
            "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "action_type": action_type,
            "skill":       skill,
            "source":      source,
            "destination": destination,
            "outcome":     outcome,
            "notes":       notes,
            "error":       error,
            "session_id":  self._session_id,
            "tier":        "gold",
        }
        self._write_json(entry)
        self._write_markdown(entry)
        return entry

    # ------------------------------------------------------------------
    # Public API — handle_error
    # ------------------------------------------------------------------

    def handle_error(
        self,
        exc: Exception,
        retry_count: int = 0,
        calling_skill: str = "unknown",
        error_level: "str | None" = None,
    ) -> dict:
        """
        Classify an exception and return the recovery action for the calling skill.

        Returns one of:
          {"action": "retry",          "wait_seconds": 30, "level": "L1"}
          {"action": "retry_after_fix",                    "level": "L2"}
          {"action": "pause_skill",    "escalation": ...,  "level": "L3"}
          {"action": "halt_loop",                          "level": "L4"}
        """
        message = str(exc)
        level   = error_level or self._classify_error(message)

        if level == "L1":
            return self._recover_l1(message, retry_count, calling_skill)
        elif level == "L2":
            return self._recover_l2(message, calling_skill)
        elif level == "L3":
            return self._recover_l3(message, calling_skill)
        else:
            return self._recover_l4(message, calling_skill)

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    def _classify_error(self, message: str) -> str:
        """Classify error level from exception message text."""
        msg = message.lower()
        # L4 — Critical: vault-level or system failures
        if any(k in msg for k in [
            "critical", "vault path", "corrupted", "permission denied",
            "disk full", "readonly filesystem", "oserror",
        ]):
            return "L4"
        # L3 — Escalatable: auth / session / permissions
        if any(k in msg for k in [
            "auth", "login", "session", "403", "401",
            "unauthorized", "forbidden",
            "target page closed", "targetclosed", "browser closed",
            "playwright:", "net::err",
        ]):
            return "L3"
        # L2 — Recoverable: file / format issues
        if any(k in msg for k in [
            "yaml", "frontmatter", "filenotfound", "no such file",
            "parsing error", "decode", "unicodeerror",
        ]):
            return "L2"
        # L1 — Transient: network / rate limit
        return "L1"

    # ------------------------------------------------------------------
    # Recovery helpers
    # ------------------------------------------------------------------

    def _recover_l1(self, message: str, retry_count: int, skill: str) -> dict:
        """L1: retry after 30s; escalate after 3 attempts."""
        if retry_count >= 2:
            self.logger.warning(f"L1 exhausted after {retry_count + 1} retries — escalating")
            return self._recover_l3(f"L1 exhausted ({retry_count + 1} retries): {message}", skill)

        self.log_action(
            "RECOVER", skill, f"skill/{skill}", None, "success",
            notes=f"level: L1 | action: retry after 30s | attempt: {retry_count + 1}",
        )
        self.logger.info(f"L1 error — retry {retry_count + 1} in 30s: {message[:80]}")
        return {"action": "retry", "wait_seconds": 30, "level": "L1", "retry_count": retry_count + 1}

    def _recover_l2(self, message: str, skill: str) -> dict:
        """L2: attempt auto-fix (frontmatter / missing file), then retry."""
        self.log_action(
            "RECOVER", skill, f"skill/{skill}", None, "success",
            notes=f"level: L2 | action: retry_after_fix | {message[:120]}",
        )
        self.logger.info(f"L2 error — auto-fix and retry: {message[:80]}")
        return {"action": "retry_after_fix", "level": "L2"}

    def _recover_l3(self, message: str, skill: str) -> dict:
        """L3: create escalation note, pause this skill (others continue)."""
        note_path = self._create_escalation_note(skill, message, "L3")
        dest = str(note_path.relative_to(self.vault_path)) if note_path else None

        self.log_action(
            "ESCALATE", skill, f"skill/{skill}", dest, "failed",
            notes=f"level: L3 | reason: {message[:120]}",
            error={"message": message, "level": "L3", "recovery_action": "escalated"},
        )
        self.logger.error(f"L3 escalation — pausing {skill}: {message[:80]}")
        return {"action": "pause_skill", "level": "L3", "escalation": str(note_path or "")}

    def _recover_l4(self, message: str, skill: str) -> dict:
        """L4: critical — create escalation, update Dashboard, halt loop."""
        note_path = self._create_escalation_note(skill, message, "L4")
        self._update_dashboard_critical(skill, message)

        self.log_action(
            "ESCALATE", skill, f"skill/{skill}", "Dashboard.md", "failed",
            notes=f"level: L4 CRITICAL | halt_loop | {message[:120]}",
            error={"message": message, "level": "L4", "recovery_action": "halt_loop"},
        )
        self.logger.critical(f"L4 CRITICAL — halting loop: {message[:80]}")
        return {"action": "halt_loop", "level": "L4", "escalation": str(note_path or "")}

    # ------------------------------------------------------------------
    # Helpers — escalation note + dashboard
    # ------------------------------------------------------------------

    def _create_escalation_note(self, skill: str, message: str, level: str) -> "Path | None":
        """Write an escalation note to Needs_Action/."""
        try:
            self.needs_action_path.mkdir(parents=True, exist_ok=True)
            now      = datetime.now()
            filename = f"{now.strftime('%Y-%m-%d %H-%M')} — Escalation-{skill}.md"
            path     = self.needs_action_path / filename
            summary  = message[:200].replace('"', "'")
            priority = "critical" if level == "L4" else "high"
            guidance = (
                "Re-authenticate the platform session and restart the poster script. "
                "Check watcher/ logs for details."
            )
            content = (
                f"---\n"
                f"title: \"Escalation: {skill} — {summary[:60]}\"\n"
                f"type: escalation\n"
                f"skill: {skill}\n"
                f"error_level: {level}\n"
                f"error: \"{summary[:150]}\"\n"
                f"action_required: \"Human must resolve: {guidance}\"\n"
                f"status: pending\n"
                f"priority: {priority}\n"
                f"created: {now.strftime('%Y-%m-%d')}\n"
                f"domain: business\n"
                f"tags: [escalation, {level.lower()}, {skill}]\n"
                f"---\n\n"
                f"# Escalation: {skill}\n\n"
                f"**Error Level:** {level}  \n"
                f"**Skill:** {skill}  \n"
                f"**Time:** {now.strftime('%Y-%m-%d %H:%M:%S')}  \n\n"
                f"## Error Details\n\n"
                f"```\n{message[:500]}\n```\n\n"
                f"## Action Required\n\n"
                f"{guidance}\n"
            )
            path.write_text(content, encoding="utf-8")
            self.logger.info(f"Escalation note created: {filename}")
            return path
        except Exception as e:
            self.logger.error(f"Failed to write escalation note: {e}")
            return None

    def _update_dashboard_critical(self, skill: str, message: str) -> None:
        """Append a critical alert line to Dashboard.md."""
        try:
            dashboard = self.vault_path / "Dashboard.md"
            if not dashboard.exists():
                return
            now   = datetime.now().strftime("%Y-%m-%d %H:%M")
            alert = f"\n> ⚠️ **CRITICAL** [{now}] — `{skill}`: {message[:100]}\n"
            with open(dashboard, "a", encoding="utf-8") as f:
                f.write(alert)
        except Exception as e:
            self.logger.error(f"Failed to update Dashboard.md with critical alert: {e}")

    # ------------------------------------------------------------------
    # File I/O — JSON log
    # ------------------------------------------------------------------

    def _write_json(self, entry: dict) -> None:
        """Append entry to Logs/YYYY-MM-DD.json (array format, append-safe)."""
        self.logs_path.mkdir(parents=True, exist_ok=True)
        today     = datetime.now().strftime("%Y-%m-%d")
        json_file = self.logs_path / f"{today}.json"
        try:
            if json_file.exists():
                text = json_file.read_text(encoding="utf-8").strip()
                try:
                    entries = json.loads(text) if text else []
                    if not isinstance(entries, list):
                        entries = [entries]
                except json.JSONDecodeError:
                    entries = []  # corrupted — start fresh list (keep old file content)
            else:
                entries = []
            entries.append(entry)
            json_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            # Graceful degradation: log warning, rely on Markdown log
            self.logger.warning(f"JSON log write failed (Markdown fallback active): {e}")

    # ------------------------------------------------------------------
    # File I/O — Markdown log
    # ------------------------------------------------------------------

    def _write_markdown(self, entry: dict) -> None:
        """Append Bronze-format line to Logs/YYYY-MM-DD.md."""
        self.logs_path.mkdir(parents=True, exist_ok=True)
        today   = datetime.now().strftime("%Y-%m-%d")
        md_file = self.logs_path / f"{today}.md"
        try:
            ts           = entry["timestamp"].split("T")[1] if "T" in entry["timestamp"] else entry["timestamp"]
            outcome_icon = "✅" if entry["outcome"] == "success" else "❌"
            dest_str     = f'`{entry["destination"]}`' if entry["destination"] else "—"
            line = (
                f"- `{ts}` | **{entry['action_type']}** | "
                f"`{entry['source']}` → {dest_str} | "
                f"{outcome_icon} {entry['outcome']} | {entry.get('notes', '')}\n"
            )
            if not md_file.exists():
                header = (
                    f"---\ntitle: \"Agent Log — {today}\"\ndate: {today}\n"
                    f"tags: [log, agent, gold]\n---\n\n"
                    f"# Agent Log — {today}\n\n"
                    f"> Append-only. Do not edit existing entries.\n\n---\n\n"
                )
                md_file.write_text(header, encoding="utf-8")
            with open(md_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            self.logger.warning(f"Markdown log write failed: {e}")

    # ------------------------------------------------------------------
    # Convenience query helpers
    # ------------------------------------------------------------------

    def get_todays_errors(self) -> list:
        """Return all ERROR and ESCALATE entries from today's JSON log."""
        today     = datetime.now().strftime("%Y-%m-%d")
        json_file = self.logs_path / f"{today}.json"
        if not json_file.exists():
            return []
        try:
            entries = json.loads(json_file.read_text(encoding="utf-8"))
            return [e for e in entries if e.get("action_type") in ("ERROR", "ESCALATE")]
        except Exception:
            return []

    def get_week_entries(self, date_prefix: str) -> list:
        """Return all JSON log entries for a given week (files matching date_prefix like '2026-02-')."""
        entries = []
        if not self.logs_path.exists():
            return entries
        for f in sorted(self.logs_path.glob(f"{date_prefix}*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    entries.extend(data)
            except Exception:
                continue
        return entries
