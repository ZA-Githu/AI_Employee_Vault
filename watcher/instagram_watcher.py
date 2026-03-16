"""
instagram_watcher.py
--------------------
Gold Tier — Instagram Watcher using Playwright.

Monitors Instagram for:
  - Unread Direct Messages (DMs)
  - Activity: mentions in posts/stories, comments on your posts,
    new followers, story reactions

Routes each item to:
  - Needs_Action/  — DMs/mentions with trigger keywords
  - Inbox/         — general activity without trigger keywords

Uses its own persistent session at sessions/instagram-watcher/
(separate from instagram_poster.py to avoid Chrome profile lock conflicts).

Run:
    python instagram_watcher.py                  # continuous watch
    python instagram_watcher.py --dry-run        # detect only, no vault writes
    python instagram_watcher.py --once           # single pass, then exit
    python instagram_watcher.py --interval 180   # poll every 3 minutes

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python instagram_watcher.py               # browser opens, sign into Instagram once
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
INSTAGRAM_URL    = "https://www.instagram.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "instagram-watcher"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
DEFAULT_INTERVAL = int(os.getenv("INSTAGRAM_WATCH_INTERVAL", "300"))
BODY_MAX_CHARS   = 600

_raw_keywords = os.getenv(
    "INSTAGRAM_KEYWORDS",
    "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,collab,collaboration,brand,deal,sponsor",
)
TRIGGER_KEYWORDS: list[str] = [k.strip().lower() for k in _raw_keywords.split(",") if k.strip()]


class InstagramWatcher(BaseWatcher):
    """
    Watches Instagram for new DMs and activity (mentions, comments, follows).
    Routes each item to Needs_Action/ or Inbox/ based on keyword triggers.
    Uses a persistent Playwright browser context separate from InstagramPoster.
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
        return safe[:max_len] if safe else "ig-item"

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
        lowered = text.lower()
        for kw in TRIGGER_KEYWORDS:
            if kw in lowered:
                return "Needs_Action"
        return "Inbox"

    # ------------------------------------------------------------------
    # Note builders
    # ------------------------------------------------------------------

    def _build_dm_note(self, sender: str, preview: str) -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe    = self._sanitispythone(sender)
        excerpt = (preview[:BODY_MAX_CHARS] + " …") if len(preview) > BODY_MAX_CHARS else preview
        dest    = self._classify(preview)
        priority = "high" if dest == "Needs_Action" else "medium"

        filename = f"{file_ts} — IG-dm-{safe}.md"
        content  = (
            f"---\n"
            f"title: \"Instagram DM: {sender}\"\n"
            f"type: instagram-dm\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"from: \"{sender}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [instagram, dm, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Instagram DM: {sender}\n\n"
            f"> **From:** {sender}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Message Preview\n\n"
            f"{excerpt if excerpt else '_No preview available._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review DM from {sender}\n"
            f"- [ ] Decide: reply / ignore / escalate\n"
            f"- [ ] Open Instagram Direct to reply\n"
        )
        return filename, content, dest

    def _build_activity_note(self, text: str, activity_type: str) -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        short   = self._sanitise(text[:40])
        excerpt = (text[:BODY_MAX_CHARS] + " …") if len(text) > BODY_MAX_CHARS else text
        dest    = self._classify(text)
        priority = "high" if dest == "Needs_Action" else "low"

        # mentions and comments always go to Needs_Action
        if activity_type in ("mention", "comment"):
            dest = "Needs_Action"
            priority = "high"

        filename = f"{file_ts} — IG-{activity_type}-{short}.md"
        content  = (
            f"---\n"
            f"title: \"Instagram {activity_type.capitalize()}: {text[:50]}\"\n"
            f"type: instagram-{activity_type}\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [instagram, {activity_type}, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Instagram {activity_type.capitalize()}\n\n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Activity\n\n"
            f"{excerpt}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review {activity_type}\n"
            f"- [ ] Respond if needed via Instagram\n"
        )
        return filename, content, dest

    # ------------------------------------------------------------------
    # Instagram browser helpers
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        try:
            page.wait_for_selector(
                'svg[aria-label="Instagram"], nav[role="navigation"], '
                'a[href="/direct/inbox/"], [aria-label="Home"]',
                timeout=10_000,
            )
            self.logger.info("Instagram: logged in.")
            return True
        except PWTimeout:
            pass

        self.logger.info("Instagram: not logged in. Waiting for manual login ...")
        self.logger.info("  → Please sign into Instagram in the browser window.")
        try:
            page.wait_for_selector(
                'nav[role="navigation"], a[href="/direct/inbox/"], [aria-label="Home"]',
                timeout=LOGIN_TIMEOUT_MS,
            )
            self.logger.info("Instagram: login detected.")
            return True
        except PWTimeout:
            self.logger.error("Instagram login timed out.")
            return False

    def _get_unread_dms(self, page) -> "list[dict]":
        """
        Navigate to Instagram DMs and collect unread message threads.
        Returns list of dicts: {sender, preview}
        """
        dms = []
        try:
            page.goto(INSTAGRAM_URL + "/direct/inbox/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2500)

            # Find DM thread rows
            thread_selectors = [
                'div[role="listbox"] > div',
                '[aria-label="Direct"] div[role="button"]',
                'div[class*="x1n2onr6"] a[href*="/direct/t/"]',
                'a[href*="/direct/t/"]',
            ]
            threads = []
            for sel in thread_selectors:
                found = page.query_selector_all(sel)
                if found and len(found) > 0:
                    threads = found[:10]
                    break

            for thread in threads:
                try:
                    # Get sender name
                    name_el = thread.query_selector(
                        'span[dir="auto"]:first-of-type, '
                        'span[style*="font-weight"]:first-of-type, '
                        'div > span:first-child'
                    )
                    # Get last message preview
                    preview_el = thread.query_selector(
                        'span[dir="auto"]:nth-of-type(2), '
                        'span[color="secondary"]:first-of-type'
                    )
                    sender  = name_el.inner_text().strip() if name_el else ""
                    preview = preview_el.inner_text().strip() if preview_el else ""

                    # Look for unread indicator (blue dot or bold text)
                    unread = thread.query_selector(
                        '[aria-label*="Unread"], '
                        'div[style*="background-color: rgb(0, 149, 246)"]'
                    )
                    bold = thread.query_selector('span[style*="font-weight: 600"], strong')

                    if (unread or bold) and sender and sender not in ("Message", ""):
                        dms.append({"sender": sender, "preview": preview})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching Instagram DMs: {exc}")

        return dms

    def _get_activity(self, page) -> "list[dict]":
        """
        Navigate to Instagram Activity (notifications) and collect recent items.
        Returns list of dicts: {text, type}
        """
        activities = []
        try:
            page.goto(INSTAGRAM_URL + "/activity/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2500)

            # Fallback: use the notification bell from home page
            if page.url != INSTAGRAM_URL + "/activity/" and "/activity" not in page.url:
                page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
                page.wait_for_timeout(1500)
                try:
                    page.click('[aria-label="Notifications"], a[href="/activity/"]', timeout=5000)
                    page.wait_for_timeout(2000)
                except PWTimeout:
                    pass

            activity_selectors = [
                '[role="main"] [role="button"] span[dir="auto"]',
                'div[aria-label="Notifications"] span',
                'div[class*="x1n2onr6"] span[dir="auto"]',
            ]
            seen_texts: set[str] = set()
            for sel in activity_selectors:
                items = page.query_selector_all(sel)
                if items:
                    for item in items[:20]:
                        try:
                            text = item.inner_text().strip()
                            if text and len(text) > 5 and text not in seen_texts:
                                seen_texts.add(text)
                                # Classify activity type
                                lower = text.lower()
                                atype = "notification"
                                if "mention" in lower or "@" in text:
                                    atype = "mention"
                                elif "comment" in lower:
                                    atype = "comment"
                                elif "follow" in lower:
                                    atype = "follow"
                                elif "like" in lower or "liked" in lower:
                                    atype = "like"
                                elif "story" in lower:
                                    atype = "story-reaction"
                                activities.append({"text": text, "type": atype})
                                if len(activities) >= 15:
                                    break
                        except Exception:
                            continue
                    if activities:
                        break

        except Exception as exc:
            self.logger.warning(f"Error fetching Instagram activity: {exc}")

        return activities

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_dms(self, dms: "list[dict]") -> int:
        processed = 0
        for item in dms:
            sender  = item["sender"]
            preview = item["preview"]
            try:
                filename, content, dest = self._build_dm_note(sender, preview)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.audit.log_action(
                        "CREATE", "instagram-watcher",
                        f"instagram-dm:{sender}", f"{dest}/{filename}",
                        notes=f"from: {sender} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"instagram-dm:{sender}", f"{dest}/{filename}",
                        notes=f"Instagram DM from {sender}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing DM from {sender}: {exc}")
                self._error_count += 1
        return processed

    def _process_activity(self, activities: "list[dict]") -> int:
        processed = 0
        for item in activities:
            text  = item["text"]
            atype = item["type"]
            # Skip likes — low value, high noise
            if atype == "like":
                continue
            try:
                filename, content, dest = self._build_activity_note(text, atype)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.audit.log_action(
                        "CREATE", "instagram-watcher",
                        f"instagram-{atype}", f"{dest}/{filename}",
                        notes=f"type: {atype} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"instagram-{atype}", f"{dest}/{filename}",
                        notes=f"Instagram {atype} routed to {dest}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing {atype}: {exc}")
                self._error_count += 1
        return processed

    def _check_once(self, page) -> int:
        """Run one full check cycle. Returns total items processed."""
        total = 0

        self.logger.info("Checking Instagram DMs ...")
        dms = self._get_unread_dms(page)
        if dms:
            self.logger.info(f"Found {len(dms)} unread DM(s).")
            total += self._process_dms(dms)
        else:
            self.logger.info("No unread DMs.")

        self.logger.info("Checking Instagram activity ...")
        activities = self._get_activity(page)
        if activities:
            self.logger.info(f"Found {len(activities)} activity item(s).")
            total += self._process_activity(activities)
        else:
            self.logger.info("No new activity.")

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
            "SKILL_RUN", "instagram-watcher", "skills/social-poster.md",
            notes=f"InstagramWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 375, "height": 812},   # mobile viewport for Instagram
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
                args=["--no-sandbox"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.once:
                    self.logger.info("Single-pass mode.")
                    self._check_once(page)
                else:
                    self.logger.info(f"Watching Instagram every {self.interval}s. Ctrl+C to stop.\n")
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
        print("  InstagramWatcher stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Processed  : {self._processed_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "instagram-watcher", "skills/social-poster.md",
            notes=f"InstagramWatcher stopped — duration: {duration}, processed: {self._processed_count}",
        )

    def _print_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Instagram Watcher")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Session     : {SESSION_DIR}")
        print(f"  Keywords    : {', '.join(TRIGGER_KEYWORDS[:6])} ...")
        print(f"  Interval    : {self.interval}s")
        print(f"  Monitors    : DMs + Mentions + Comments + Follows")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Instagram Watcher")
    p.add_argument("--dry-run",  action="store_true", help="Detect items, no vault writes")
    p.add_argument("--once",     action="store_true", help="Single pass then exit")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval (seconds)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    InstagramWatcher(interval=args.interval, once=args.once).start()
