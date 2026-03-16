"""
facebook_watcher.py
-------------------
Gold Tier — Facebook Watcher using Playwright.

Monitors Facebook for:
  - Unread Messenger messages
  - Unread notifications (mentions, comments, tags, page alerts)

Routes each item to:
  - Needs_Action/  — messages/notifications with trigger keywords
  - Inbox/         — general items without trigger keywords

Uses its own persistent session at sessions/facebook-watcher/
(separate from facebook_poster.py to avoid Chrome profile lock conflicts).

Run:
    python facebook_watcher.py                  # continuous watch
    python facebook_watcher.py --dry-run        # detect only, no vault writes
    python facebook_watcher.py --once           # single pass, then exit
    python facebook_watcher.py --interval 120   # poll every 2 minutes

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python facebook_watcher.py               # browser opens, sign into Facebook once
"""

import os
import re
import time
import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from base_watcher import BaseWatcher
from audit_logger import AuditLogger

# ── Config ────────────────────────────────────────────────────
FACEBOOK_URL     = "https://www.facebook.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "facebook-watcher"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
DEFAULT_INTERVAL = int(os.getenv("FACEBOOK_WATCH_INTERVAL", "300"))
BODY_MAX_CHARS   = 600

# Keywords that trigger Needs_Action/ routing (case-insensitive)
_raw_keywords = os.getenv(
    "FACEBOOK_KEYWORDS",
    "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,client,invoice,project",
)
TRIGGER_KEYWORDS: list[str] = [k.strip().lower() for k in _raw_keywords.split(",") if k.strip()]


class FacebookWatcher(BaseWatcher):
    """
    Watches Facebook for new messages and notifications.
    Routes each item to Needs_Action/ or Inbox/ based on keyword triggers.
    Uses a persistent Playwright browser context separate from FacebookPoster.
    """

    def __init__(self, interval: int = DEFAULT_INTERVAL, once: bool = False):
        super().__init__()
        self.interval         = max(60, interval)
        self.once             = once
        self._running         = False
        self._processed_count = 0
        self._error_count     = 0
        self._start_time: "datetime | None" = None

        self.audit = AuditLogger(self.vault_path)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Vault helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitise(text: str, max_len: int = 60) -> str:
        safe = re.sub(r'[\\/*?:"<>|\n\r]', " ", text).strip()
        safe = re.sub(r"\s+", "-", safe)
        return safe[:max_len] if safe else "fb-item"

    def _write_note(self, folder: Path, filename: str, content: str) -> "Path | None":
        dest = folder / filename
        if dest.exists():
            ts   = datetime.now().strftime("%H%M%S")
            dest = folder / f"{Path(filename).stem}-{ts}.md"
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

    def _build_message_note(self, sender: str, preview: str) -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe    = self._sanitise(sender)
        excerpt = (preview[:BODY_MAX_CHARS] + " …") if len(preview) > BODY_MAX_CHARS else preview
        dest    = self._classify(preview)
        priority = "high" if dest == "Needs_Action" else "medium"

        filename = f"{file_ts} — FB-msg-{safe}.md"
        content  = (
            f"---\n"
            f"title: \"Facebook Message: {sender}\"\n"
            f"type: facebook-message\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"from: \"{sender}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [facebook, message, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Facebook Message: {sender}\n\n"
            f"> **From:** {sender}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Message Preview\n\n"
            f"{excerpt if excerpt else '_No preview available._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review message from {sender}\n"
            f"- [ ] Decide: reply / ignore / escalate\n"
            f"- [ ] Open Facebook Messenger to reply\n"
        )
        return filename, content, dest

    def _build_notification_note(self, text: str, notif_type: str = "notification") -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        short   = self._sanitise(text[:40])
        excerpt = (text[:BODY_MAX_CHARS] + " …") if len(text) > BODY_MAX_CHARS else text
        dest    = self._classify(text)
        priority = "high" if dest == "Needs_Action" else "low"

        filename = f"{file_ts} — FB-{notif_type}-{short}.md"
        content  = (
            f"---\n"
            f"title: \"Facebook {notif_type.capitalize()}: {text[:50]}\"\n"
            f"type: facebook-{notif_type}\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [facebook, {notif_type}, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Facebook {notif_type.capitalize()}\n\n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Content\n\n"
            f"{excerpt}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review {notif_type}\n"
            f"- [ ] Respond if needed via Facebook\n"
        )
        return filename, content, dest

    # ------------------------------------------------------------------
    # Facebook browser helpers
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        """Check if logged in; wait for manual login if not."""
        try:
            page.wait_for_selector(
                'div[role="feed"], [aria-label="Facebook"], '
                '[data-testid="royal_blue_bar"], [aria-label="Create"]',
                timeout=10_000,
            )
            self.logger.info("Facebook: logged in.")
            return True
        except PWTimeout:
            pass

        self.logger.info("Facebook: not logged in. Waiting for manual login ...")
        self.logger.info("  → Please sign into Facebook in the browser window.")
        try:
            page.wait_for_selector(
                'div[role="feed"], [aria-label="Facebook"], '
                '[data-testid="royal_blue_bar"], [aria-label="Create"]',
                timeout=LOGIN_TIMEOUT_MS,
            )
            self.logger.info("Facebook: login detected.")
            return True
        except PWTimeout:
            self.logger.error("Facebook login timed out.")
            return False

    def _get_unread_messages(self, page) -> "list[dict]":
        """
        Navigate to Messenger and collect unread message previews.
        Returns list of dicts: {sender, preview}
        """
        messages = []
        try:
            page.goto(FACEBOOK_URL + "/messages/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2500)

            # Find unread conversation threads
            thread_selectors = [
                'div[aria-label*="unread"]',
                'a[href*="/messages/t/"][aria-label]',
                'div[data-testid="mwthreadlist-item"]',
                '[role="row"]',
            ]
            threads = []
            for sel in thread_selectors:
                found = page.query_selector_all(sel)
                if found:
                    threads = found[:10]
                    break

            for thread in threads:
                try:
                    # Get sender name from aria-label or inner text
                    aria = thread.get_attribute("aria-label") or ""
                    name_el = thread.query_selector(
                        'span[dir="auto"], [data-testid="mwthreadlist-item-title"]'
                    )
                    preview_el = thread.query_selector(
                        'span[dir="auto"]:nth-child(2), [data-testid="mwthreadlist-item-message"]'
                    )
                    sender  = name_el.inner_text().strip() if name_el else aria[:40] or "Unknown"
                    preview = preview_el.inner_text().strip() if preview_el else ""

                    # Only include threads with actual unread indicator
                    unread_dot = thread.query_selector('[aria-label*="Unread"], [data-testid*="unread"]')
                    bold_name  = thread.query_selector('span[style*="font-weight: 600"], strong')

                    if (unread_dot or bold_name) and sender and sender != "Unknown":
                        messages.append({"sender": sender, "preview": preview})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching Facebook messages: {exc}")

        return messages

    def _get_notifications(self, page) -> "list[dict]":
        """
        Navigate to Facebook Notifications and collect unread items.
        Returns list of dicts: {text, type}
        """
        notifications = []
        try:
            page.goto(FACEBOOK_URL + "/notifications/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2500)

            # Find notification items
            notif_selectors = [
                '[role="article"] [dir="auto"]',
                '[data-testid="notif-item"] span',
                'div[aria-label*="notification"]',
                'a[href*="/notification"]',
            ]
            seen_texts: set[str] = set()
            for sel in notif_selectors:
                items = page.query_selector_all(sel)
                if items:
                    for item in items[:20]:
                        try:
                            text = item.inner_text().strip()
                            if text and len(text) > 5 and text not in seen_texts:
                                seen_texts.add(text)
                                # Determine notification type from content
                                ntype = "notification"
                                lower = text.lower()
                                if "comment" in lower:
                                    ntype = "comment"
                                elif "mention" in lower or "tagged" in lower:
                                    ntype = "mention"
                                elif "like" in lower or "react" in lower:
                                    ntype = "reaction"
                                elif "message" in lower:
                                    ntype = "message"
                                notifications.append({"text": text, "type": ntype})
                                if len(notifications) >= 15:
                                    break
                        except Exception:
                            continue
                    if notifications:
                        break

        except Exception as exc:
            self.logger.warning(f"Error fetching Facebook notifications: {exc}")

        return notifications

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_messages(self, messages: "list[dict]") -> int:
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
                    self.audit.log_action(
                        "CREATE", "facebook-watcher",
                        f"facebook-msg:{sender}", f"{dest}/{filename}",
                        notes=f"from: {sender} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"facebook-msg:{sender}", f"{dest}/{filename}",
                        notes=f"Facebook message from {sender}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing message from {sender}: {exc}")
                self._error_count += 1
        return processed

    def _process_notifications(self, notifications: "list[dict]") -> int:
        processed = 0
        for item in notifications:
            text    = item["text"]
            ntype   = item["type"]
            try:
                filename, content, dest = self._build_notification_note(text, ntype)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.audit.log_action(
                        "CREATE", "facebook-watcher",
                        f"facebook-{ntype}", f"{dest}/{filename}",
                        notes=f"type: {ntype} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"facebook-{ntype}", f"{dest}/{filename}",
                        notes=f"Facebook {ntype} routed to {dest}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing {ntype}: {exc}")
                self._error_count += 1
        return processed

    def _check_once(self, page) -> int:
        """Run one full check cycle. Returns total items processed."""
        total = 0

        self.logger.info("Checking Facebook messages ...")
        msgs = self._get_unread_messages(page)
        if msgs:
            self.logger.info(f"Found {len(msgs)} unread message(s).")
            total += self._process_messages(msgs)
        else:
            self.logger.info("No unread messages.")

        self.logger.info("Checking Facebook notifications ...")
        notifs = self._get_notifications(page)
        if notifs:
            self.logger.info(f"Found {len(notifs)} notification(s).")
            total += self._process_notifications(notifs)
        else:
            self.logger.info("No new notifications.")

        return total

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.ensure_folders()
        self._print_banner()
        self._start_time = datetime.now()
        self._running    = True

        self.audit.log_action(
            "SKILL_RUN", "facebook-watcher", "skills/social-poster.md",
            notes=f"FacebookWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1366, "height": 900},
                args=["--no-sandbox"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(FACEBOOK_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.once:
                    self.logger.info("Single-pass mode.")
                    self._check_once(page)
                else:
                    self.logger.info(f"Watching Facebook every {self.interval}s. Ctrl+C to stop.\n")
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
        print("  FacebookWatcher stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Processed  : {self._processed_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "facebook-watcher", "skills/social-poster.md",
            notes=f"FacebookWatcher stopped — duration: {duration}, processed: {self._processed_count}",
        )

    def _print_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Facebook Watcher")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Session     : {SESSION_DIR}")
        print(f"  Keywords    : {', '.join(TRIGGER_KEYWORDS[:6])} ...")
        print(f"  Interval    : {self.interval}s")
        print(f"  Monitors    : Messages + Notifications")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Facebook Watcher")
    p.add_argument("--dry-run",  action="store_true", help="Detect items, no vault writes")
    p.add_argument("--once",     action="store_true", help="Single pass then exit")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval (seconds)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    FacebookWatcher(interval=args.interval, once=args.once).start()
