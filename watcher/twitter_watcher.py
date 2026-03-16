"""
twitter_watcher.py
------------------
Gold Tier — Twitter / X Watcher using Playwright.

Monitors Twitter / X for:
  - Unread Direct Messages (DMs)
  - Mentions (@username in tweets/replies)
  - Notifications (replies, quote tweets, follows, likes on your tweets)

Routes each item to:
  - Needs_Action/  — DMs/mentions with trigger keywords
  - Inbox/         — general notifications without trigger keywords

Mentions always go to Needs_Action/ regardless of keywords.

Uses its own persistent session at sessions/twitter-watcher/
(separate from twitter_poster.py to avoid Chrome profile lock conflicts).

Run:
    python twitter_watcher.py                  # continuous watch
    python twitter_watcher.py --dry-run        # detect only, no vault writes
    python twitter_watcher.py --once           # single pass, then exit
    python twitter_watcher.py --interval 180   # poll every 3 minutes

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python twitter_watcher.py               # browser opens, sign into X once
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
TWITTER_URL      = "https://x.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "twitter-watcher"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
DEFAULT_INTERVAL = int(os.getenv("TWITTER_WATCH_INTERVAL", "300"))
BODY_MAX_CHARS   = 600

_raw_keywords = os.getenv(
    "TWITTER_KEYWORDS",
    "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,dm,collab,sponsor,feature,hire,job",
)
TRIGGER_KEYWORDS: list[str] = [k.strip().lower() for k in _raw_keywords.split(",") if k.strip()]


class TwitterWatcher(BaseWatcher):
    """
    Watches Twitter/X for new DMs, mentions, and notifications.
    Routes each item to Needs_Action/ or Inbox/ based on keyword triggers.
    Mentions always go to Needs_Action/.
    Uses a persistent Playwright browser context separate from TwitterPoster.
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
        return safe[:max_len] if safe else "tw-item"

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
        safe    = self._sanitise(sender)
        excerpt = (preview[:BODY_MAX_CHARS] + " …") if len(preview) > BODY_MAX_CHARS else preview
        dest    = self._classify(preview)
        priority = "high" if dest == "Needs_Action" else "medium"

        filename = f"{file_ts} — TW-dm-{safe}.md"
        content  = (
            f"---\n"
            f"title: \"Twitter DM: {sender}\"\n"
            f"type: twitter-dm\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"from: \"{sender}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [twitter, dm, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Twitter DM: {sender}\n\n"
            f"> **From:** {sender}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Message Preview\n\n"
            f"{excerpt if excerpt else '_No preview available._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review DM from {sender}\n"
            f"- [ ] Decide: reply / ignore / escalate\n"
            f"- [ ] Open X (Twitter) Messages to reply\n"
        )
        return filename, content, dest

    def _build_mention_note(self, user: str, tweet_text: str) -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        safe    = self._sanitise(user)
        excerpt = (tweet_text[:BODY_MAX_CHARS] + " …") if len(tweet_text) > BODY_MAX_CHARS else tweet_text

        # Mentions always go to Needs_Action
        filename = f"{file_ts} — TW-mention-{safe}.md"
        content  = (
            f"---\n"
            f"title: \"Twitter Mention by @{user}\"\n"
            f"type: twitter-mention\n"
            f"status: pending\n"
            f"priority: high\n"
            f"from: \"@{user}\"\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [twitter, mention, needs-action, agent]\n"
            f"---\n\n"
            f"# Twitter Mention by @{user}\n\n"
            f"> **From:** @{user}  \n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Tweet\n\n"
            f"{excerpt if excerpt else '_No content available._'}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review mention from @{user}\n"
            f"- [ ] Decide: reply / like / quote tweet / ignore\n"
            f"- [ ] Open X (Twitter) Notifications to respond\n"
        )
        return filename, content, "Needs_Action"

    def _build_notification_note(self, text: str, notif_type: str) -> "tuple[str, str, str]":
        today   = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        file_ts = datetime.now().strftime("%Y-%m-%d %H-%M")
        short   = self._sanitise(text[:40])
        excerpt = (text[:BODY_MAX_CHARS] + " …") if len(text) > BODY_MAX_CHARS else text
        dest    = self._classify(text)
        priority = "high" if dest == "Needs_Action" else "low"

        filename = f"{file_ts} — TW-{notif_type}-{short}.md"
        content  = (
            f"---\n"
            f"title: \"Twitter {notif_type.capitalize()}: {text[:50]}\"\n"
            f"type: twitter-{notif_type}\n"
            f"status: pending\n"
            f"priority: {priority}\n"
            f"received: \"{now_str}\"\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"domain: business\n"
            f"agent_assigned: claude\n"
            f"tags: [twitter, {notif_type}, {dest.lower().replace('_', '-')}, agent]\n"
            f"---\n\n"
            f"# Twitter {notif_type.capitalize()}\n\n"
            f"> **Received:** {now_str}  \n\n"
            f"---\n\n"
            f"## Content\n\n"
            f"{excerpt}\n\n"
            f"---\n\n"
            f"## Actions Required\n\n"
            f"- [ ] Review {notif_type}\n"
            f"- [ ] Respond if needed via X (Twitter)\n"
        )
        return filename, content, dest

    # ------------------------------------------------------------------
    # Twitter / X browser helpers
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        try:
            page.wait_for_selector(
                '[data-testid="SideNav_NewTweet_Button"], '
                '[data-testid="primaryColumn"], '
                'a[aria-label="Home"]',
                timeout=10_000,
            )
            self.logger.info("Twitter/X: logged in.")
            return True
        except PWTimeout:
            pass

        self.logger.info("Twitter/X: not logged in. Waiting for manual login ...")
        self.logger.info("  → Please sign into X (Twitter) in the browser window.")
        try:
            page.wait_for_selector(
                '[data-testid="SideNav_NewTweet_Button"], '
                '[data-testid="primaryColumn"], '
                'a[aria-label="Home"]',
                timeout=LOGIN_TIMEOUT_MS,
            )
            self.logger.info("Twitter/X: login detected.")
            return True
        except PWTimeout:
            self.logger.error("Twitter/X login timed out.")
            return False

    def _get_unread_dms(self, page) -> "list[dict]":
        """
        Navigate to X Messages and collect unread DM threads.
        Returns list of dicts: {sender, preview}
        """
        dms = []
        try:
            page.goto(TWITTER_URL + "/messages", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2500)

            # Find DM conversation items
            conv_selectors = [
                '[data-testid="conversation"]',
                'div[aria-label*="Direct message"]',
                'a[href*="/messages/"]',
            ]
            conversations = []
            for sel in conv_selectors:
                found = page.query_selector_all(sel)
                if found:
                    conversations = found[:10]
                    break

            for conv in conversations:
                try:
                    # Get sender name
                    name_el = conv.query_selector(
                        '[data-testid="User-Name"] span, '
                        'span[dir="ltr"]:first-of-type, '
                        'div[dir="ltr"] > span'
                    )
                    # Get message preview
                    preview_el = conv.query_selector(
                        '[data-testid="tweetText"], '
                        'span[dir="auto"]:last-of-type'
                    )
                    sender  = name_el.inner_text().strip() if name_el else ""
                    preview = preview_el.inner_text().strip() if preview_el else ""

                    # Check for unread badge
                    unread_badge = conv.query_selector(
                        '[data-testid="unread-count"], '
                        'div[style*="background-color: rgb(29, 155, 240)"]'
                    )
                    if unread_badge and sender:
                        dms.append({"sender": sender, "preview": preview})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching Twitter DMs: {exc}")

        return dms

    def _get_mentions(self, page) -> "list[dict]":
        """
        Navigate to X Mentions tab and collect recent mentions.
        Returns list of dicts: {user, tweet_text}
        """
        mentions = []
        try:
            page.goto(TWITTER_URL + "/notifications", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Click Mentions tab if available
            try:
                page.click('a[href="/notifications/mentions"], div[role="tab"]:has-text("Mentions")', timeout=5000)
                page.wait_for_timeout(2000)
            except PWTimeout:
                pass

            # Collect tweet articles that mention the user
            tweet_articles = page.query_selector_all('[data-testid="tweet"]')
            for article in tweet_articles[:10]:
                try:
                    user_el = article.query_selector(
                        '[data-testid="User-Name"] span:first-of-type, '
                        'span[dir="ltr"] > span'
                    )
                    text_el = article.query_selector('[data-testid="tweetText"]')
                    user     = user_el.inner_text().strip() if user_el else "unknown"
                    tweet_text = text_el.inner_text().strip() if text_el else ""
                    if tweet_text and "@" in tweet_text:
                        mentions.append({"user": user, "tweet_text": tweet_text})
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching Twitter mentions: {exc}")

        return mentions

    def _get_notifications(self, page) -> "list[dict]":
        """
        Navigate to X Notifications (All) and collect recent items.
        Returns list of dicts: {text, type}
        """
        notifications = []
        try:
            page.goto(TWITTER_URL + "/notifications", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Click All tab
            try:
                page.click('a[href="/notifications"], div[role="tab"]:has-text("All")', timeout=5000)
                page.wait_for_timeout(1500)
            except PWTimeout:
                pass

            notif_items = page.query_selector_all('[data-testid="cellInnerDiv"]')
            seen_texts: set[str] = set()
            for item in notif_items[:20]:
                try:
                    text_el = item.query_selector('[data-testid="tweetText"], span[dir="auto"]')
                    text    = text_el.inner_text().strip() if text_el else item.inner_text().strip()
                    text    = text[:300]  # cap length

                    if text and len(text) > 5 and text not in seen_texts:
                        seen_texts.add(text)
                        lower = text.lower()
                        ntype = "notification"
                        if "mention" in lower or "@" in text:
                            ntype = "mention"
                        elif "reply" in lower or "replied" in lower:
                            ntype = "reply"
                        elif "retweet" in lower or "retweeted" in lower or "quoted" in lower:
                            ntype = "retweet"
                        elif "follow" in lower or "followed" in lower:
                            ntype = "follow"
                        elif "like" in lower or "liked" in lower:
                            ntype = "like"

                        # Skip likes/follows — too noisy
                        if ntype in ("like", "follow"):
                            continue

                        notifications.append({"text": text, "type": ntype})
                        if len(notifications) >= 15:
                            break
                except Exception:
                    continue

        except Exception as exc:
            self.logger.warning(f"Error fetching Twitter notifications: {exc}")

        return notifications

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
                        "CREATE", "twitter-watcher",
                        f"twitter-dm:{sender}", f"{dest}/{filename}",
                        notes=f"from: {sender} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"twitter-dm:{sender}", f"{dest}/{filename}",
                        notes=f"Twitter DM from {sender}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing DM from {sender}: {exc}")
                self._error_count += 1
        return processed

    def _process_mentions(self, mentions: "list[dict]") -> int:
        processed = 0
        for item in mentions:
            user       = item["user"]
            tweet_text = item["tweet_text"]
            try:
                filename, content, dest = self._build_mention_note(user, tweet_text)
                note = self._write_note(self.needs_action_path, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ Needs_Action/{filename}")
                    self.audit.log_action(
                        "CREATE", "twitter-watcher",
                        f"twitter-mention:@{user}", f"Needs_Action/{filename}",
                        notes=f"mention by @{user}",
                    )
                    self.log_to_vault(
                        "CREATE", f"twitter-mention:@{user}", f"Needs_Action/{filename}",
                        notes=f"Twitter mention by @{user}",
                    )
                    self._processed_count += 1
                    processed += 1
            except Exception as exc:
                self.logger.error(f"Error processing mention from {user}: {exc}")
                self._error_count += 1
        return processed

    def _process_notifications(self, notifications: "list[dict]") -> int:
        processed = 0
        for item in notifications:
            text  = item["text"]
            ntype = item["type"]
            try:
                filename, content, dest = self._build_notification_note(text, ntype)
                folder = self.needs_action_path if dest == "Needs_Action" else self.inbox_path
                note   = self._write_note(folder, filename, content)
                if note or self.dry_run:
                    self.logger.info(f"✅ {dest}/{filename}")
                    self.audit.log_action(
                        "CREATE", "twitter-watcher",
                        f"twitter-{ntype}", f"{dest}/{filename}",
                        notes=f"type: {ntype} | routed: {dest}",
                    )
                    self.log_to_vault(
                        "CREATE", f"twitter-{ntype}", f"{dest}/{filename}",
                        notes=f"Twitter {ntype} routed to {dest}",
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

        self.logger.info("Checking Twitter/X DMs ...")
        dms = self._get_unread_dms(page)
        if dms:
            self.logger.info(f"Found {len(dms)} unread DM(s).")
            total += self._process_dms(dms)
        else:
            self.logger.info("No unread DMs.")

        self.logger.info("Checking Twitter/X mentions ...")
        mentions = self._get_mentions(page)
        if mentions:
            self.logger.info(f"Found {len(mentions)} mention(s).")
            total += self._process_mentions(mentions)
        else:
            self.logger.info("No new mentions.")

        self.logger.info("Checking Twitter/X notifications ...")
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
            "SKILL_RUN", "twitter-watcher", "skills/social-poster.md",
            notes=f"TwitterWatcher started — interval={self.interval}s dry_run={self.dry_run}",
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1366, "height": 900},
                args=["--no-sandbox"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(TWITTER_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.once:
                    self.logger.info("Single-pass mode.")
                    self._check_once(page)
                else:
                    self.logger.info(f"Watching Twitter/X every {self.interval}s. Ctrl+C to stop.\n")
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
        print("  TwitterWatcher stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Processed  : {self._processed_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "twitter-watcher", "skills/social-poster.md",
            notes=f"TwitterWatcher stopped — duration: {duration}, processed: {self._processed_count}",
        )

    def _print_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Twitter / X Watcher")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode        : {mode}")
        print(f"  Vault       : {self.vault_path}")
        print(f"  Session     : {SESSION_DIR}")
        print(f"  Keywords    : {', '.join(TRIGGER_KEYWORDS[:6])} ...")
        print(f"  Interval    : {self.interval}s")
        print(f"  Monitors    : DMs + Mentions + Replies + Retweets")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Twitter / X Watcher")
    p.add_argument("--dry-run",  action="store_true", help="Detect items, no vault writes")
    p.add_argument("--once",     action="store_true", help="Single pass then exit")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Poll interval (seconds)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    TwitterWatcher(interval=args.interval, once=args.once).start()
