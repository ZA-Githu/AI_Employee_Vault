"""
whatsapp_watcher.py
-------------------
Silver Tier — WhatsApp Web Watcher using Playwright.

- Persistent browser session (QR scan only once; session saved to sessions/)
- Polls WhatsApp Web for new unread messages
- Keyword triggers route messages to Needs_Action/
- All other unread messages land in Inbox/
- Sensitive actions (draft replies) go to Pending_Approval/ — never sent automatically

Run:
    python whatsapp_watcher.py              # continuous watch
    python whatsapp_watcher.py --dry-run    # detect only, no vault writes
    python whatsapp_watcher.py --once       # single pass, then exit
    python whatsapp_watcher.py --interval 60

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python whatsapp_watcher.py           # scan QR on first run
"""

import os
import re
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from base_watcher import BaseWatcher

# ── Config ────────────────────────────────────────────────────
WHATSAPP_URL      = "https://web.whatsapp.com"
SESSION_DIR       = Path(__file__).parent / "sessions" / "whatsapp"
QR_TIMEOUT_MS     = 120_000   # 2 min to scan QR on first run
PAGE_LOAD_MS      = 30_000
DEFAULT_INTERVAL  = int(os.getenv("WHATSAPP_POLL_INTERVAL", "60"))
BODY_MAX_CHARS    = 600

# Keywords that trigger Needs_Action/ routing (case-insensitive)
_raw_keywords = os.getenv(
    "WHATSAPP_KEYWORDS",
    "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap",
)
TRIGGER_KEYWORDS: list[str] = [k.strip().lower() for k in _raw_keywords.split(",") if k.strip()]


class WhatsAppWatcher(BaseWatcher):
    """
    Watches WhatsApp Web for new unread messages and routes them into the vault.
    Uses a persistent Playwright browser context so QR code is scanned only once.
    """

    def __init__(self, interval: int = DEFAULT_INTERVAL, once: bool = False):
        super().__init__()
        self.interval         = max(30, interval)
        self.once             = once
        self._running         = False
        self._processed_count = 0
        self._error_count     = 0
        self._start_time: datetime | None = None

        # Silver Tier paths
        self.plans_path            = self.vault_path / "Plans"
        self.pending_approval_path = self.vault_path / "Pending_Approval"

        SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Vault helpers
    # ------------------------------------------------------------------

    def _ensure_silver_folders(self) -> None:
        for folder in [self.plans_path, self.pending_approval_path]:
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"Created folder: {folder.name}/")

    @staticmethod
    def _sanitise(text: str, max_len: int = 60) -> str:
        safe = re.sub(r'[\\/*?:"<>|\n\r]', " ", text).strip()
        safe = re.sub(r"\s+", "-", safe)
        return safe[:max_len] if safe else "whatsapp-message"

    def _write_note(self, folder: Path, filename: str, content: str) -> Path | None:
        dest = folder / filename
        if dest.exists():
            stem = Path(filename).stem
            ts   = datetime.now().strftime("%H%M%S")
            dest = folder / f"{stem}-{ts}.md"

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would write: {folder.name}/{dest.name}")
            return None

        dest.write_text(content, encoding="utf-8")
        return dest

    def _build_message_note(
        self,
        contact: str,
        messages: list[str],
        destination: str,  # "Needs_Action" | "Inbox"
    ) -> tuple[str, str]:
        """Return (filename, markdown_content) for a WhatsApp message batch."""
        today     = datetime.now().strftime("%Y-%m-%d")
        now_str   = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts   = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe_name = self._sanitise(contact)
        filename  = f"{file_ts} — WA-{safe_name}.md"
        combined  = "\n".join(messages)
        excerpt   = (combined[:BODY_MAX_CHARS] + " …") if len(combined) > BODY_MAX_CHARS else combined
        priority  = "high" if destination == "Needs_Action" else "medium"
        status    = "pending" if destination == "Needs_Action" else "unread"

        content = (
            f"---\n"
            f"title: \"WhatsApp: {contact}\"\n"
            f"type: whatsapp-message\n"
            f"status: {status}\n"
            f"priority: {priority}\n"
            f"from: \"{contact}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"agent_assigned: claude\n"
            f"tags: [whatsapp, {destination.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# WhatsApp: {contact}\n\n"
            f"> **From:** {contact}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Messages\n\n"
            f"{excerpt}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review message from {contact}\n"
            f"- [ ] Decide: reply / ignore / escalate\n"
            f"- [ ] To draft a reply: say `draft whatsapp reply to {contact}`\n"
        )
        return filename, content

    def _build_reply_plan(self, contact: str, original: str) -> tuple[str, str]:
        """Create a Pending_Approval plan file for a WhatsApp reply."""
        today     = datetime.now().strftime("%Y-%m-%d")
        file_ts   = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe_name = self._sanitise(contact)
        filename  = f"{file_ts} — Reply-to-{safe_name}.md"

        content = (
            f"---\n"
            f"title: \"Reply to {contact} on WhatsApp\"\n"
            f"type: whatsapp-reply\n"
            f"status: pending-approval\n"
            f"priority: medium\n"
            f"to: \"{contact}\"\n"
            f"created: {today}\n"
            f"submitted: {today}\n"
            f"awaiting_review_by: human\n"
            f"author: claude\n"
            f"tags: [whatsapp, reply, pending-approval]\n"
            f"---\n\n"
            f"# Reply to {contact} on WhatsApp\n\n"
            f"## Original Message\n\n"
            f"{original[:400]}\n\n"
            f"---\n\n"
            f"## Proposed Reply\n\n"
            f"> _(Claude: fill in suggested reply here before submitting)_\n\n"
            f"---\n\n"
            f"## Approval\n\n"
            f"- Approve: `approve plan {filename}`\n"
            f"- Reject:  `reject plan {filename}`\n"
        )
        return filename, content

    # ------------------------------------------------------------------
    # Playwright helpers
    # ------------------------------------------------------------------

    def _wait_for_whatsapp_ready(self, page) -> bool:
        """Wait until the WhatsApp Web chat list is visible."""
        self.logger.info("Waiting for WhatsApp Web to load ...")
        try:
            # The side panel with chats is the reliable "ready" indicator
            page.wait_for_selector(
                '[data-testid="chat-list"], [aria-label="Chat list"], #pane-side',
                timeout=QR_TIMEOUT_MS,
            )
            self.logger.info("WhatsApp Web ready.")
            return True
        except PWTimeout:
            self.logger.error("WhatsApp Web did not load in time. Check QR scan or session.")
            return False

    def _get_unread_chats(self, page) -> list[dict]:
        """
        Find all chats with unread messages.
        Returns list of dicts: {name, element_handle}
        """
        unread = []
        try:
            # Multiple selector patterns for resilience across WhatsApp Web versions
            selectors = [
                '[data-testid="unread-count"]',
                'span[aria-label*="unread"]',
                '.unread-count',
            ]
            for selector in selectors:
                badges = page.query_selector_all(selector)
                if badges:
                    for badge in badges:
                        try:
                            # Walk up to the parent chat row
                            chat_row = badge.evaluate_handle(
                                "el => el.closest('[data-testid=\"cell-frame-container\"],"
                                "[role=\"listitem\"], .chat-row, ._2nY6U') || el.parentElement"
                            )
                            name_el = chat_row.query_selector(
                                '[data-testid="cell-frame-title"], '
                                '[aria-label="Chat name"] span, '
                                '.zoWT4, ._1wjpf'
                            )
                            name = name_el.inner_text() if name_el else "Unknown Contact"
                            unread.append({"name": name.strip(), "row": chat_row})
                        except Exception:
                            continue
                    if unread:
                        break
        except Exception as exc:
            self.logger.warning(f"Error finding unread chats: {exc}")
        return unread

    def _read_chat_messages(self, page, chat_row) -> list[str]:
        """
        Click on a chat row and read the last N incoming messages.
        Returns list of message text strings.
        """
        messages = []
        try:
            chat_row.click()
            page.wait_for_timeout(1500)

            # Read incoming messages (not sent by us)
            msg_selectors = [
                '[data-testid="msg-container"] [data-testid="msg-text"]',
                '.message-in .selectable-text',
                '[class*="message-in"] span[class*="selectable"]',
            ]
            for sel in msg_selectors:
                els = page.query_selector_all(sel)
                if els:
                    # Take last 10 messages
                    for el in els[-10:]:
                        try:
                            text = el.inner_text().strip()
                            if text:
                                messages.append(text)
                        except Exception:
                            continue
                    break
        except Exception as exc:
            self.logger.warning(f"Error reading messages: {exc}")
        return messages

    def _classify_messages(self, messages: list[str]) -> str:
        """Return 'Needs_Action' or 'Inbox' based on keyword triggers."""
        combined = " ".join(messages).lower()
        for keyword in TRIGGER_KEYWORDS:
            if keyword in combined:
                return "Needs_Action"
        return "Inbox"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_unread_chats(self, page) -> int:
        """Process all unread chats. Returns count processed."""
        unread_chats = self._get_unread_chats(page)
        if not unread_chats:
            self.logger.info("No unread messages found.")
            return 0

        self.logger.info(f"Found {len(unread_chats)} unread chat(s).")
        processed = 0

        for chat in unread_chats:
            contact  = chat["name"]
            messages = self._read_chat_messages(page, chat["row"])

            if not messages:
                self.logger.warning(f"No messages extracted from chat: {contact}")
                continue

            destination = self._classify_messages(messages)
            folder      = self.needs_action_path if destination == "Needs_Action" else self.inbox_path
            filename, content = self._build_message_note(contact, messages, destination)

            dest = self._write_note(folder, filename, content)
            if dest:
                self.logger.info(f"✅ {destination}/{dest.name}")
                self.log_to_vault(
                    "CREATE",
                    f"whatsapp:{contact}",
                    f"{destination}/{dest.name}",
                    notes=f"from: {contact} | msgs: {len(messages)} | keywords: {destination == 'Needs_Action'}",
                )
                self._processed_count += 1
                processed += 1

        return processed

    # ------------------------------------------------------------------
    # Reply plan creation (called externally or from CLI)
    # ------------------------------------------------------------------

    def create_reply_plan(self, contact: str, original_message: str) -> Path | None:
        """
        Draft a WhatsApp reply plan and place it in Pending_Approval/.
        The agent never sends the reply — human must approve first.
        """
        self._ensure_silver_folders()
        filename, content = self._build_reply_plan(contact, original_message)

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would create reply plan: Pending_Approval/{filename}")
            return None

        dest = self.pending_approval_path / filename
        dest.write_text(content, encoding="utf-8")
        self.logger.info(f"📋 Reply plan created: Pending_Approval/{filename}")
        self.log_to_vault(
            "PLAN_SUBMIT",
            f"whatsapp:{contact}",
            f"Pending_Approval/{filename}",
            notes=f"Reply draft awaiting human approval — to: {contact}",
        )
        return dest

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.ensure_folders()
        self._ensure_silver_folders()
        self._print_wa_banner()
        self._start_time = datetime.now()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/whatsapp-watcher.md",
            notes=f"WhatsAppWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        self._running = True

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,          # WhatsApp Web requires visible browser
                viewport={"width": 1280, "height": 900},
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_whatsapp_ready(page):
                browser.close()
                self.stop()
                return

            try:
                if self.once:
                    self.logger.info("Single-pass mode.")
                    self._process_unread_chats(page)
                else:
                    self.logger.info(f"Watching WhatsApp every {self.interval}s. Ctrl+C to stop.\n")
                    while self._running:
                        count = self._process_unread_chats(page)
                        if count:
                            self.logger.info(f"Cycle complete — {count} chat(s) processed.")
                        for _ in range(self.interval):
                            if not self._running:
                                break
                            time.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("Keyboard interrupt received.")
            finally:
                browser.close()
                self.stop()

    def stop(self) -> None:
        self._running = False
        duration = ""
        if self._start_time:
            secs     = int((datetime.now() - self._start_time).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s"

        print()
        print("=" * 60)
        print("  WhatsAppWatcher stopped.")
        print(f"  Session duration : {duration}")
        print(f"  Chats processed  : {self._processed_count}")
        print(f"  Errors           : {self._error_count}")
        print("=" * 60)
        print()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/whatsapp-watcher.md",
            notes=f"WhatsAppWatcher stopped — duration: {duration}, processed: {self._processed_count}",
        )

    def _print_wa_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — WhatsApp Watcher")
        print("  Silver Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Session     : {SESSION_DIR}")
        print(f"  Keywords    : {', '.join(TRIGGER_KEYWORDS[:5])} ...")
        print(f"  Interval    : {self.interval}s")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Silver Tier — WhatsApp Web Watcher")
    p.add_argument("--dry-run",  action="store_true", help="Detect messages, no vault writes")
    p.add_argument("--once",     action="store_true", help="Single pass then exit")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval (seconds)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    WhatsAppWatcher(interval=args.interval, once=args.once).start()
