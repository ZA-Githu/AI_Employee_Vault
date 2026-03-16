"""
linkedin_watcher.py
-------------------
Silver Tier — LinkedIn Watcher using Playwright.

Monitors LinkedIn for:
  - Unread messages (LinkedIn Messaging)
  - Pending connection requests
  - Notifications mentioning keywords (job, urgent, meeting, etc.)

Routes each item to:
  - Needs_Action/  — messages with trigger keywords, connection requests, important notifications
  - Inbox/         — general notifications and messages without trigger keywords

Uses its own persistent session at sessions/linkedin-watcher/
(separate from linkedin_poster.py to avoid Chrome profile lock conflicts).

Run:
    python linkedin_watcher.py                  # continuous watch
    python linkedin_watcher.py --dry-run        # detect only, no vault writes
    python linkedin_watcher.py --once           # single pass, then exit
    python linkedin_watcher.py --interval 120   # poll every 2 minutes

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python linkedin_watcher.py               # browser opens, sign into LinkedIn once
       (session is shared with linkedin_poster.py)
"""

import os
import re
import time
import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from base_watcher import BaseWatcher

# ── Config ────────────────────────────────────────────────────
LINKEDIN_URL     = "https://www.linkedin.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "linkedin-watcher"
LOGIN_TIMEOUT_MS = 60_000
PAGE_LOAD_MS     = 30_000
DEFAULT_INTERVAL = int(os.getenv("LINKEDIN_POLL_INTERVAL", "300"))
BODY_MAX_CHARS   = 600

# Keywords that trigger Needs_Action/ routing (case-insensitive)
_raw_keywords = os.getenv(
    "LINKEDIN_KEYWORDS",
    "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,job,offer,interview,opportunity",
)
TRIGGER_KEYWORDS: list[str] = [k.strip().lower() for k in _raw_keywords.split(",") if k.strip()]


class LinkedInWatcher(BaseWatcher):
    """
    Watches LinkedIn for new messages, connection requests, and notifications.
    Routes each item to Needs_Action/ or Inbox/ based on keyword triggers.
    Uses a persistent Playwright browser context shared with LinkedInPoster.
    """

    def __init__(self, interval: int = DEFAULT_INTERVAL, once: bool = False):
        super().__init__()
        self.interval         = max(60, interval)
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
        return safe[:max_len] if safe else "linkedin-item"

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

    def _classify(self, text: str) -> str:
        """Return 'Needs_Action' or 'Inbox' based on keyword triggers."""
        lowered = text.lower()
        for kw in TRIGGER_KEYWORDS:
            if kw in lowered:
                return "Needs_Action"
        return "Inbox"

    # ------------------------------------------------------------------
    # Note builders
    # ------------------------------------------------------------------

    def _build_message_note(self, sender: str, preview: str) -> tuple[str, str]:
        today    = datetime.now().strftime("%Y-%m-%d")
        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts  = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe     = self._sanitise(sender)
        filename = f"{file_ts} — LI-msg-{safe}.md"
        excerpt  = (preview[:BODY_MAX_CHARS] + " …") if len(preview) > BODY_MAX_CHARS else preview
        dest     = self._classify(preview)
        priority = "high" if dest == "Needs_Action" else "medium"

        content = (
            f"---\n"
            f"title: \"LinkedIn Message: {sender}\"\n"
            f"type: linkedin-message\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"from: \"{sender}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"agent_assigned: claude\n"
            f"tags: [linkedin, message, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# LinkedIn Message: {sender}\n\n"
            f"> **From:** {sender}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Message Preview\n\n"
            f"{excerpt if excerpt else '_No preview available._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review message from {sender}\n"
            f"- [ ] Decide: reply / ignore / escalate\n"
            f"- [ ] Open LinkedIn Messaging to reply\n"
        )
        return filename, content, dest

    def _build_connection_note(self, name: str, headline: str) -> tuple[str, str, str]:
        today    = datetime.now().strftime("%Y-%m-%d")
        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts  = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe     = self._sanitise(name)
        filename = f"{file_ts} — LI-connect-{safe}.md"

        content = (
            f"---\n"
            f"title: \"LinkedIn Connection Request: {name}\"\n"
            f"type: linkedin-connection\n"
            f"status: pending\n"
            f"priority: medium\n"
            f"from: \"{name}\"\n"
            f"headline: \"{headline}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"agent_assigned: claude\n"
            f"tags: [linkedin, connection, needs-action, agent]\n"
            f"---\n\n"
            f"# LinkedIn Connection Request: {name}\n\n"
            f"> **From:** {name}  \n"
            f"> **Headline:** {headline}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review connection request from {name}\n"
            f"- [ ] Decide: accept / ignore / message first\n"
            f"- [ ] Open LinkedIn My Network to respond\n"
        )
        return filename, content, "Needs_Action"

    def _build_notification_note(self, text: str) -> tuple[str, str, str]:
        today    = datetime.now().strftime("%Y-%m-%d")
        now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts  = datetime.now().strftime("%Y-%m-%d %H-%M")
        short    = self._sanitise(text[:40])
        filename = f"{file_ts} — LI-notif-{short}.md"
        excerpt  = (text[:BODY_MAX_CHARS] + " …") if len(text) > BODY_MAX_CHARS else text
        dest     = self._classify(text)
        priority = "high" if dest == "Needs_Action" else "low"

        content = (
            f"---\n"
            f"title: \"LinkedIn Notification\"\n"
            f"type: linkedin-notification\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"agent_assigned: claude\n"
            f"tags: [linkedin, notification, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# LinkedIn Notification\n\n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Notification\n\n"
            f"{excerpt}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review notification\n"
            f"- [ ] Respond if needed\n"
        )
        return filename, content, dest

    # ------------------------------------------------------------------
    # LinkedIn browser helpers
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        """Check if logged in; if not, wait for manual login."""
        try:
            page.wait_for_selector(
                '[data-control-name="feed_nav_home"], .feed-identity-module, '
                '[aria-label="Home"], .share-box-feed-entry__trigger',
                timeout=10_000,
            )
            self.logger.info("LinkedIn: logged in.")
            return True
        except PWTimeout:
            pass

        self.logger.info("LinkedIn: not logged in. Waiting for manual login ...")
        self.logger.info("  → Please sign into LinkedIn in the browser window.")
        try:
            page.wait_for_selector(
                '[data-control-name="feed_nav_home"], .feed-identity-module, '
                '.share-box-feed-entry__trigger',
                timeout=LOGIN_TIMEOUT_MS,
            )
            self.logger.info("LinkedIn: login detected.")
            return True
        except PWTimeout:
            self.logger.error("LinkedIn login timed out.")
            return False

    def _get_unread_messages(self, page) -> list[dict]:
        """
        Navigate to LinkedIn Messaging and collect unread message previews.
        Returns list of dicts: {sender, preview}
        """
        messages = []
        try:
            page.goto(LINKEDIN_URL + "/messaging/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Find unread conversation threads
            unread_selectors = [
                '[data-control-name="overlay.open_conversation"] .msg-conversation-listitem__unread-count',
                '.msg-conversation-listitem--unread',
                'li[data-control-name="overlay.open_conversation"][aria-selected="false"]',
            ]
            threads = []
            for sel in unread_selectors:
                found = page.query_selector_all(sel)
                if found:
                    threads = found
                    break

            for thread in threads[:10]:   # cap at 10 per cycle
                try:
                    # Get sender name
                    name_el = thread.query_selector(
                        '.msg-conversation-listitem__participant-names, '
                        '[data-control-name="overlay.open_conversation"] .truncate'
                    )
                    # Get message preview
                    preview_el = thread.query_selector(
                        '.msg-conversation-listitem__message-snippet, '
                        '.msg-conversation-card__message-snippet'
                    )
                    sender  = name_el.inner_text().strip() if name_el else "Unknown"
                    preview = preview_el.inner_text().strip() if preview_el else ""
                    if sender and sender != "Unknown":
                        messages.append({"sender": sender, "preview": preview})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching LinkedIn messages: {exc}")

        return messages

    def _get_connection_requests(self, page) -> list[dict]:
        """
        Navigate to My Network and collect pending connection requests.
        Returns list of dicts: {name, headline}
        """
        connections = []
        try:
            page.goto(LINKEDIN_URL + "/mynetwork/invitation-manager/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Find pending invitation cards
            invite_cards = page.query_selector_all(
                '.invitation-card, [data-view-name="invitation-card-list-item"]'
            )
            for card in invite_cards[:10]:   # cap at 10 per cycle
                try:
                    name_el     = card.query_selector(
                        '.invitation-card__title, [data-view-name="invitation-card-title"]'
                    )
                    headline_el = card.query_selector(
                        '.invitation-card__subtitle, [data-view-name="invitation-card-subtitle"]'
                    )
                    name     = name_el.inner_text().strip() if name_el else "Unknown"
                    headline = headline_el.inner_text().strip() if headline_el else ""
                    if name and name != "Unknown":
                        connections.append({"name": name, "headline": headline})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching LinkedIn connections: {exc}")

        return connections

    def _get_notifications(self, page) -> list[str]:
        """
        Navigate to LinkedIn Notifications and collect recent unread items.
        Returns list of notification text strings.
        """
        texts = []
        try:
            page.goto(LINKEDIN_URL + "/notifications/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            notif_selectors = [
                '.nt-card--unread .nt-card__text',
                '[data-finite-scroll-hotspot="true"] .artdeco-card.nt-card--unread',
                '.notification-item--unread .notification-item__content',
            ]
            for sel in notif_selectors:
                items = page.query_selector_all(sel)
                if items:
                    for item in items[:15]:   # cap at 15 per cycle
                        try:
                            text = item.inner_text().strip()
                            if text:
                                texts.append(text)
                        except Exception:
                            continue
                    break

        except Exception as exc:
            self.logger.warning(f"Error fetching LinkedIn notifications: {exc}")

        return texts

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_messages(self, messages: list[dict]) -> int:
        processed = 0
        for item in messages:
            sender  = item["sender"]
            preview = item["preview"]
            try:
                filename, content, dest = self._build_message_note(sender, preview)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.log_to_vault(
                        "CREATE",
                        f"linkedin-msg:{sender}",
                        f"{dest}/{filename}",
                        notes=f"from: {sender} | keywords: {dest == 'Needs_Action'}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing message from {sender}: {exc}")
                self._error_count += 1
        return processed

    def _process_connections(self, connections: list[dict]) -> int:
        processed = 0
        for item in connections:
            name     = item["name"]
            headline = item["headline"]
            try:
                filename, content, dest = self._build_connection_note(name, headline)
                note = self._write_note(self.needs_action_path, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ Needs_Action/{filename}")
                    self.log_to_vault(
                        "CREATE",
                        f"linkedin-connect:{name}",
                        f"Needs_Action/{filename}",
                        notes=f"connection request from: {name}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing connection from {name}: {exc}")
                self._error_count += 1
        return processed

    def _process_notifications(self, notifications: list[str]) -> int:
        processed = 0
        for text in notifications:
            try:
                filename, content, dest = self._build_notification_note(text)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.log_to_vault(
                        "CREATE",
                        "linkedin-notification",
                        f"{dest}/{filename}",
                        notes=f"notification routed to {dest}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing notification: {exc}")
                self._error_count += 1
        return processed

    def _check_once(self, page) -> int:
        """Run one full check cycle. Returns total items processed."""
        total = 0

        self.logger.info("Checking LinkedIn messages ...")
        msgs = self._get_unread_messages(page)
        if msgs:
            self.logger.info(f"Found {len(msgs)} unread message(s).")
            total += self._process_messages(msgs)
        else:
            self.logger.info("No unread messages.")

        self.logger.info("Checking connection requests ...")
        conns = self._get_connection_requests(page)
        if conns:
            self.logger.info(f"Found {len(conns)} connection request(s).")
            total += self._process_connections(conns)
        else:
            self.logger.info("No pending connection requests.")

        self.logger.info("Checking notifications ...")
        notifs = self._get_notifications(page)
        if notifs:
            self.logger.info(f"Found {len(notifs)} unread notification(s).")
            total += self._process_notifications(notifs)
        else:
            self.logger.info("No new notifications.")

        return total

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.ensure_folders()
        self._ensure_silver_folders()
        self._print_li_watcher_banner()
        self._start_time = datetime.now()
        self._running    = True

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/linkedin-poster.md",
            notes=f"LinkedInWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1366, "height": 900},
                args=["--no-sandbox"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(LINKEDIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.once:
                    self.logger.info("Single-pass mode.")
                    self._check_once(page)
                else:
                    self.logger.info(f"Watching LinkedIn every {self.interval}s. Ctrl+C to stop.\n")
                    while self._running:
                        count = self._check_once(page)
                        if count:
                            self.logger.info(f"Cycle complete — {count} item(s) processed.")
                        else:
                            self.logger.info("Cycle complete — nothing new.")
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
        print("  LinkedInWatcher stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Processed  : {self._processed_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/linkedin-poster.md",
            notes=f"LinkedInWatcher stopped — duration: {duration}, processed: {self._processed_count}, errors: {self._error_count}",
        )

    def _print_li_watcher_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — LinkedIn Watcher")
        print("  Silver Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Session     : {SESSION_DIR}")
        print(f"  Keywords    : {', '.join(TRIGGER_KEYWORDS[:6])} ...")
        print(f"  Interval    : {self.interval}s")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Silver Tier — LinkedIn Watcher")
    p.add_argument("--dry-run",  action="store_true", help="Detect items, no vault writes")
    p.add_argument("--once",     action="store_true", help="Single pass then exit")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval (seconds)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    LinkedInWatcher(interval=args.interval, once=args.once).start()
