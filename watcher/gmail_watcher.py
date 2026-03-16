"""
gmail_watcher.py
----------------
Silver Tier — Gmail Watcher.

Monitors unread IMPORTANT Gmail messages, creates a structured .md note
in Needs_Action/ for each one, then marks the email as read.

Extends BaseWatcher (base_watcher.py) for vault logging, path resolution,
and consistent startup/shutdown behaviour.

Setup (one-time):
    1. Place credentials.json in the watcher/ folder
       (download from Google Cloud Console → OAuth 2.0 Client ID)
    2. pip install -r requirements.txt
    3. python gmail_watcher.py   ← opens browser on first run to authorise

Run:
    python watcher/gmail_watcher.py
    python gmail_watcher.py --dry-run      # detect emails, no vault writes
    python gmail_watcher.py --once         # single pass, then exit
    python gmail_watcher.py --interval 120 # poll every 2 minutes
"""

import os
import re
import sys
import time
import base64
import argparse
import html
from datetime import datetime
from pathlib import Path
from email.utils import parseaddr

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from base_watcher import BaseWatcher

# ── Gmail API scope ───────────────────────────────────────────
# gmail.modify allows: read messages + add/remove labels (mark as read)
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# ── Gmail query to find target emails ────────────────────────
# Fetches UNREAD emails labelled IMPORTANT (Google's auto-priority)
GMAIL_QUERY = "is:unread label:important"

# Maximum body characters to store in the vault note
BODY_MAX_CHARS = 800

# Default poll interval (seconds) — overridden by .env or CLI
DEFAULT_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL", "300"))


# ──────────────────────────────────────────────────────────────
# GmailWatcher
# ──────────────────────────────────────────────────────────────

class GmailWatcher(BaseWatcher):
    """
    Silver Tier watcher that polls Gmail for unread important emails
    and routes each one into Needs_Action/ as a structured Markdown note.
    """

    def __init__(self, interval: int = DEFAULT_INTERVAL, once: bool = False):
        super().__init__()
        self.interval          = max(60, interval)   # enforce 60s minimum
        self.once              = once                 # single-pass mode
        self._running          = False
        self._service          = None                 # Gmail API client
        self._processed_count  = 0
        self._error_count      = 0
        self._start_time: datetime | None = None

        # Credentials file — checked in priority order
        self._creds_path  = self._find_credentials()
        self._token_path  = Path(__file__).parent / "token.json"

    # ------------------------------------------------------------------
    # Credential discovery
    # ------------------------------------------------------------------

    def _find_credentials(self) -> Path:
        """
        Look for credentials.json in this order:
          1. GMAIL_CREDENTIALS_PATH env var
          2. watcher/credentials.json
          3. vault root credentials.json
          4. Any client_secret_*.json at vault root (Google default download name)
        """
        # 1. Explicit env override
        env_path = os.getenv("GMAIL_CREDENTIALS_PATH")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return p
            self.logger.warning(f"GMAIL_CREDENTIALS_PATH set but file not found: {env_path}")

        # 2. Standard name in watcher/ folder
        p = Path(__file__).parent / "credentials.json"
        if p.exists():
            return p

        # 3. Standard name at vault root
        p = self.vault_path / "credentials.json"
        if p.exists():
            return p

        # 4. client_secret_*.json at vault root (Google Cloud Console default)
        matches = sorted(self.vault_path.glob("client_secret_*.json"))
        if matches:
            self.logger.info(f"Using credentials file: {matches[0].name}")
            return matches[0]

        # Not found — will surface error at connect time
        return Path(__file__).parent / "credentials.json"

    # ------------------------------------------------------------------
    # Gmail authentication
    # ------------------------------------------------------------------

    def _authenticate(self) -> bool:
        """
        Authenticate with Gmail using OAuth2.
        On first run, opens a browser window for the user to authorise.
        On subsequent runs, loads and refreshes the saved token.

        Returns True on success, False on failure.
        """
        if not self._creds_path.exists():
            self.logger.error(
                f"credentials.json not found at {self._creds_path}\n"
                "  Download it from Google Cloud Console:\n"
                "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
                "  Save it as 'credentials.json' in the watcher/ folder."
            )
            return False

        creds = None

        # Load saved token if it exists
        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), SCOPES
                )
            except Exception as exc:
                self.logger.warning(f"Could not load token.json: {exc} — re-authenticating.")
                creds = None

        # Refresh or run auth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    self.logger.info("Refreshing expired OAuth token ...")
                    creds.refresh(Request())
                except Exception as exc:
                    self.logger.warning(f"Token refresh failed: {exc} — re-authenticating.")
                    creds = None

            if not creds:
                self.logger.info("Opening browser for Gmail authorisation ...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._creds_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save token for next run
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
            self.logger.info(f"Token saved to {self._token_path.name}")

        try:
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            self.logger.info("Gmail API connected.")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to build Gmail service: {exc}")
            return False

    # ------------------------------------------------------------------
    # Email fetching
    # ------------------------------------------------------------------

    def _fetch_unread_important(self) -> list[dict]:
        """
        Query Gmail for unread IMPORTANT messages.
        Returns a list of message metadata dicts (id, threadId).
        """
        try:
            result = (
                self._service.users()
                .messages()
                .list(userId="me", q=GMAIL_QUERY, maxResults=50)
                .execute()
            )
            return result.get("messages", [])
        except HttpError as exc:
            self.logger.error(f"Gmail API error fetching messages: {exc}")
            self.log_to_vault(
                "ERROR",
                "gmail:inbox",
                notes=f"Gmail API fetch failed: {exc}",
                outcome="failed",
            )
            return []

    def _get_message_detail(self, msg_id: str) -> dict | None:
        """Fetch full message detail for a given message ID."""
        try:
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except HttpError as exc:
            self.logger.error(f"Could not fetch message {msg_id}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Email parsing
    # ------------------------------------------------------------------

    def _extract_header(self, headers: list[dict], name: str) -> str:
        """Extract a header value by name (case-insensitive)."""
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    def _extract_body(self, payload: dict) -> str:
        """
        Recursively extract plain-text body from the Gmail message payload.
        Falls back to HTML-stripped content if no plain text is available.
        """
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                if "text/html" in mime_type:
                    decoded = self._strip_html(decoded)
                return decoded
            except Exception:
                return ""

        # Multipart — recurse into parts
        for part in payload.get("parts", []):
            if "text/plain" in part.get("mimeType", ""):
                text = self._extract_body(part)
                if text:
                    return text

        # Second pass — accept HTML if no plain text found
        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text

        return ""

    @staticmethod
    def _strip_html(raw: str) -> str:
        """Remove HTML tags and decode HTML entities."""
        no_tags = re.sub(r"<[^>]+>", " ", raw)
        decoded = html.unescape(no_tags)
        # Collapse whitespace
        return re.sub(r"\s+", " ", decoded).strip()

    @staticmethod
    def _sanitise_filename(text: str, max_len: int = 60) -> str:
        """Convert arbitrary text to a safe filename segment."""
        safe = re.sub(r'[\\/*?:"<>|]', "", text)
        safe = re.sub(r"\s+", "-", safe.strip())
        return safe[:max_len] if safe else "no-subject"

    @staticmethod
    def _infer_priority(subject: str, snippet: str) -> str:
        """Heuristic priority from subject/snippet keywords."""
        text = (subject + " " + snippet).lower()
        if any(k in text for k in ["urgent", "critical", "asap", "immediate", "action required"]):
            return "high"
        if any(k in text for k in ["important", "deadline", "due", "review", "response needed"]):
            return "medium"
        return "medium"

    # ------------------------------------------------------------------
    # Note creation
    # ------------------------------------------------------------------

    def _build_note(self, msg: dict) -> tuple[str, str]:
        """
        Build the filename and full Markdown content for a Needs_Action note.
        Returns (filename, content).
        """
        headers  = msg.get("payload", {}).get("headers", [])
        subject  = self._extract_header(headers, "subject") or "(no subject)"
        from_raw = self._extract_header(headers, "from")    or "unknown"
        date_raw = self._extract_header(headers, "date")    or ""
        msg_id   = msg.get("id", "")
        snippet  = msg.get("snippet", "")

        # Parse sender
        sender_name, sender_email = parseaddr(from_raw)
        sender_display = f"{sender_name} <{sender_email}>" if sender_name else sender_email

        # Parse date
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_raw)
            received_str = dt.strftime("%Y-%m-%d %H:%M")
            file_date    = dt.strftime("%Y-%m-%d %H-%M")
        except Exception:
            received_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            file_date    = datetime.now().strftime("%Y-%m-%d %H-%M")

        today    = datetime.now().strftime("%Y-%m-%d")
        priority = self._infer_priority(subject, snippet)

        # Extract body
        body_full    = self._extract_body(msg.get("payload", {}))
        body_excerpt = (body_full[:BODY_MAX_CHARS] + " …") if len(body_full) > BODY_MAX_CHARS else body_full
        body_excerpt = body_excerpt.strip()

        # Build filename
        safe_subject = self._sanitise_filename(subject)
        filename = f"{file_date} — {safe_subject}.md"

        # Build content
        content = (
            f"---\n"
            f"title: \"{subject.replace(chr(34), chr(39))}\"\n"
            f"type: email\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"from: \"{sender_display.replace(chr(34), chr(39))}\"\n"
            f"email_id: \"{msg_id}\"\n"
            f"received: \"{received_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"agent_assigned: claude\n"
            f"tags: [email, needs-action, agent]\n"
            f"---\n\n"
            f"# {subject}\n\n"
            f"> **From:** {sender_display}  \n"
            f"> **Received:** {received_str}  \n"
            f"> **Email ID:** `{msg_id}`\n\n"
            f"---\n\n"
            f"## Message\n\n"
            f"{body_excerpt if body_excerpt else '_Body could not be extracted._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review email from {sender_display}\n"
            f"- [ ] Decide: reply / forward / close\n"
            f"- [ ] Close this task when resolved\n"
        )

        return filename, content

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _mark_as_read(self, msg_id: str) -> bool:
        """Remove the UNREAD label from a Gmail message."""
        try:
            self._service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return True
        except HttpError as exc:
            self.logger.error(f"Could not mark {msg_id} as read: {exc}")
            return False

    def process_email(self, msg_stub: dict) -> bool:
        """
        Full pipeline for one email:
          1. Fetch detail
          2. Build .md note
          3. Write to Needs_Action/
          4. Mark as read
          5. Log

        Returns True on success.
        """
        msg_id = msg_stub["id"]
        msg    = self._get_message_detail(msg_id)
        if not msg:
            self._error_count += 1
            return False

        headers = msg.get("payload", {}).get("headers", [])
        subject = self._extract_header(headers, "subject") or "(no subject)"
        from_hdr = self._extract_header(headers, "from") or "unknown"
        _, sender_email = parseaddr(from_hdr)

        try:
            filename, content = self._build_note(msg)
        except Exception as exc:
            self.logger.error(f"Failed to build note for {msg_id}: {exc}")
            self.log_to_vault("ERROR", f"gmail:{msg_id}", notes=f"Note build failed: {exc}", outcome="failed")
            self._error_count += 1
            return False

        dest_path = self.needs_action_path / filename

        # Handle filename collision
        if dest_path.exists():
            stem    = Path(filename).stem
            dest_path = self.needs_action_path / f"{stem}-{msg_id[:6]}.md"
            filename  = dest_path.name

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would create: Needs_Action/{filename}")
            self.log_to_vault(
                "CREATE",
                f"gmail:{msg_id}",
                f"Needs_Action/{filename}",
                notes=f"dry-run | from: {sender_email} | subject: {subject}",
            )
            return True

        # Write vault note
        try:
            dest_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            self.logger.error(f"Failed to write note {filename}: {exc}")
            self.log_to_vault("ERROR", f"gmail:{msg_id}", notes=f"Write failed: {exc}", outcome="failed")
            self._error_count += 1
            return False

        # Mark email as read
        marked = self._mark_as_read(msg_id)
        if not marked:
            self.logger.warning(f"Note written but could not mark {msg_id} as read.")

        self._processed_count += 1
        self.logger.info(f"✅ Created: Needs_Action/{filename}")

        self.log_to_vault(
            "CREATE",
            f"gmail:{msg_id}",
            f"Needs_Action/{filename}",
            notes=f"from: {sender_email} | subject: {subject} | marked_read: {marked}",
        )
        return True

    def _check_once(self) -> int:
        """Run one poll cycle. Returns count of emails processed."""
        messages = self._fetch_unread_important()

        if not messages:
            self.logger.info("No unread important emails found.")
            return 0

        self.logger.info(f"Found {len(messages)} unread important email(s). Processing ...")
        count = 0
        for stub in messages:
            if self.process_email(stub):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Authenticate, then poll Gmail continuously (or once if --once)."""
        self.ensure_folders()
        self._print_gmail_banner()

        self.logger.info("Authenticating with Gmail ...")
        if not self._authenticate():
            self.logger.error("Authentication failed. Exiting.")
            return

        self._start_time = datetime.now()
        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/gmail-watcher.md",
            notes=f"GmailWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        self._running = True

        try:
            if self.once:
                self.logger.info("Single-pass mode.")
                self._check_once()
            else:
                self.logger.info(f"Polling every {self.interval}s. Press Ctrl+C to stop.\n")
                while self._running:
                    processed = self._check_once()
                    if processed:
                        self.logger.info(f"Cycle complete — {processed} email(s) processed.")
                    self.logger.debug(f"Next check in {self.interval}s ...")
                    for _ in range(self.interval):
                        if not self._running:
                            break
                        time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Shut down cleanly and print session summary."""
        self._running = False

        duration = ""
        if self._start_time:
            secs    = int((datetime.now() - self._start_time).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s"

        print()
        print("=" * 60)
        print("  GmailWatcher stopped.")
        print(f"  Session duration  : {duration}")
        print(f"  Emails processed  : {self._processed_count}")
        print(f"  Errors            : {self._error_count}")
        print("=" * 60)
        print()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/gmail-watcher.md",
            notes=(
                f"GmailWatcher stopped — duration: {duration}, "
                f"processed: {self._processed_count}, errors: {self._error_count}"
            ),
        )

    def _print_gmail_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Gmail Watcher")
        print("  Silver Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Routing to  : {self.needs_action_path.name}/")
        print(f"  Query       : {GMAIL_QUERY}")
        print(f"  Poll interval: {self.interval}s")
        print(f"  Credentials : {self._creds_path.name}")
        print("=" * 60)
        print()


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Employee Vault — Silver Tier Gmail Watcher"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect emails but do not write vault notes or mark as read",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check pass then exit (no continuous polling)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_INTERVAL}, min: 60)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    watcher = GmailWatcher(
        interval=args.interval,
        once=args.once,
    )
    watcher.start()
