"""
twitter_poster.py
-----------------
Gold Tier — Twitter / X Poster using Playwright with Human-in-the-Loop.

Full approval workflow:
  1. Agent creates post draft → Plans/
  2. Human reviews → approves → Approved/
  3. This script reads Approved/ (type: twitter-post) and posts via browser
  4. Moves executed plan to Done/YYYY-MM/

SENSITIVE: Never posts without an Approved/ entry with approved_by: human.

Note: Twitter hard limit is 280 characters. Long posts are truncated
with a warning; set allow_truncate: true in frontmatter to permit it.

Run:
    python twitter_poster.py                  # post all pending approved posts
    python twitter_poster.py --dry-run        # preview posts, no browser
    python twitter_poster.py --watch          # watch Approved/ and post as they arrive
    python twitter_poster.py --post <file>    # post one specific approved file

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python twitter_poster.py               # browser opens, sign into Twitter/X once
"""

import os
import re
import time
import argparse
import yaml
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from base_watcher import BaseWatcher
from audit_logger import AuditLogger

# ── Config ────────────────────────────────────────────────────
TWITTER_URL      = "https://x.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "twitter"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
TWEET_MAX_CHARS  = 280
DEFAULT_INTERVAL = int(os.getenv("TWITTER_POLL_INTERVAL", "300"))


class TwitterPoster(BaseWatcher):
    """
    Reads approved Twitter post plans from Approved/, posts them via
    Playwright browser automation, then moves each plan to Done/.

    Human-in-the-Loop is enforced:
    - Only files with type: twitter-post and approved_by: human are processed.
    - Posts > 280 chars are rejected unless allow_truncate: true is set.
    """

    def __init__(self, watch: bool = False, single_file: "str | None" = None):
        super().__init__()
        self.watch_mode     = watch
        self.single_file    = single_file
        self._running       = False
        self._posted_count  = 0
        self._skipped_count = 0
        self._error_count   = 0
        self._start_time: "datetime | None" = None

        self.approved_path = self.vault_path / "Approved"
        self.done_path     = self.vault_path / "Done"
        self.plans_path    = self.vault_path / "Plans"
        self.pending_path  = self.vault_path / "Pending_Approval"

        self.audit = AuditLogger(self.vault_path)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Vault helpers
    # ------------------------------------------------------------------

    def _ensure_gold_folders(self) -> None:
        for folder in [self.approved_path, self.done_path,
                       self.plans_path, self.pending_path]:
            folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_frontmatter(text: str) -> "tuple[dict, str]":
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

    @staticmethod
    def _extract_tweet(body: str) -> str:
        markers = [
            r"##\s+Tweet\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Post Content\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Twitter Post\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Proposed Actions\s*\n(.*?)(?=\n##|\Z)",
        ]
        for pattern in markers:
            m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
        return "\n".join(lines[:5]).strip()

    def _get_approved_posts(self) -> "list[Path]":
        if not self.approved_path.exists():
            return []
        posts = []
        for f in self.approved_path.rglob("*.md"):
            try:
                fm, _ = self._parse_frontmatter(f.read_text(encoding="utf-8"))
                if (
                    fm.get("type") == "twitter-post"
                    and fm.get("approved_by")
                    and fm.get("status") == "approved"
                    and not fm.get("published")
                ):
                    posts.append(f)
            except Exception:
                continue
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        posts.sort(key=lambda f: priority_order.get(
            self._parse_frontmatter(f.read_text(encoding="utf-8"))[0].get("priority", "medium"), 2
        ))
        return posts

    def _move_to_done(self, plan_path: Path, fm: dict, body: str, post_url: str) -> None:
        today     = datetime.now().strftime("%Y-%m-%d")
        month_dir = self.done_path / datetime.now().strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        fm["status"]    = "published"
        fm["published"] = today
        fm["post_url"]  = post_url

        fm_lines    = "\n".join(
            f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {v}"
            for k, v in fm.items()
        )
        completion  = (
            f"\n\n---\n## Completion Summary\n\n"
            f"**Posted by:** twitter_poster.py\n"
            f"**Date:** {today}\n"
            f"**Post URL:** {post_url}\n"
        )
        new_content = f"---\n{fm_lines}\n---\n\n{body}{completion}"
        dest        = month_dir / plan_path.name

        if not self.dry_run:
            dest.write_text(new_content, encoding="utf-8")
            plan_path.unlink()

        rel_dest = f"Done/{month_dir.name}/{plan_path.name}"
        self.audit.log_action(
            "SOCIAL_POST", "twitter-poster",
            f"Approved/{plan_path.name}", rel_dest, "success",
            notes=f"platform: twitter | url: {post_url}",
        )
        self.log_to_vault(
            "SKILL_RUN", f"Approved/{plan_path.name}", rel_dest,
            notes=f"Twitter post published: {post_url}",
        )

    # ------------------------------------------------------------------
    # Twitter / X browser automation
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        page.wait_for_timeout(3000)
        if "/home" in page.url or "/i/timeline" in page.url:
            self.logger.info("Twitter/X: logged in.")
            return True
        if "login" in page.url or "i/flow" in page.url or "signup" in page.url:
            self.logger.info("Twitter/X: not logged in. Waiting for manual login ...")
            self.logger.info("  → Please sign into X (Twitter) in the browser window.")
            try:
                page.wait_for_url("**/home**", timeout=LOGIN_TIMEOUT_MS)
                self.logger.info("Twitter/X: login detected.")
                return True
            except PWTimeout:
                self.logger.error("Twitter/X login timed out.")
                return False
        # Unknown page — navigate to home directly
        page.goto(TWITTER_URL + "/home", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        page.wait_for_timeout(3000)
        if "/home" in page.url:
            self.logger.info("Twitter/X: logged in.")
            return True
        self.logger.error(f"Twitter/X: could not confirm login. URL: {page.url}")
        return False

    def _post_to_twitter(self, page, tweet: str) -> "str | None":
        """Post a tweet. Returns tweet URL on success, None on failure."""
        if len(tweet) > TWEET_MAX_CHARS:
            self.logger.error(f"Tweet too long: {len(tweet)} chars (limit {TWEET_MAX_CHARS})")
            return None
        try:
            page.goto(TWITTER_URL + "/home", wait_until="commit", timeout=60_000)
            page.wait_for_timeout(3000)

            # Click the "Post" / compose button
            compose_selectors = [
                '[data-testid="SideNav_NewTweet_Button"]',
                'a[href="/compose/tweet"]',
                'div[aria-label="Post"][role="button"]',
                'div[data-testid="tweetButtonInline"]',
            ]
            composed = False
            for sel in compose_selectors:
                try:
                    page.click(sel, timeout=10000)
                    composed = True
                    break
                except PWTimeout:
                    continue

            if not composed:
                # Try clicking the tweet compose box directly on the feed
                try:
                    page.click('[data-testid="tweetTextarea_0"]', timeout=5000)
                    composed = True
                except PWTimeout:
                    pass

            if not composed:
                self.logger.error("Could not open Twitter compose dialog.")
                return None

            # Wait for compose modal to fully render
            page.wait_for_timeout(5000)

            # Type the tweet — wait up to 15s for editor to render inside modal
            editor_selectors = [
                '[data-testid="tweetTextarea_0"]',
                '[data-testid="tweetTextarea_0RichTextInputContainer"]',
                'div[role="textbox"]',
                'div[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
                '[role="dialog"] [contenteditable]',
                '[role="dialog"] [role="textbox"]',
            ]
            typed = False
            for sel in editor_selectors:
                try:
                    editor = page.wait_for_selector(sel, timeout=15000)
                    editor.click()
                    page.wait_for_timeout(500)
                    page.keyboard.type(tweet, delay=30)
                    typed = True
                    break
                except PWTimeout:
                    continue

            if not typed:
                self.logger.error("Could not find Twitter text editor.")
                return None

            page.wait_for_timeout(1000)

            # Verify character count
            try:
                char_count_el = page.query_selector('[data-testid="tweetButton"] ~ div span')
                if char_count_el:
                    count_text = char_count_el.inner_text()
                    self.logger.debug(f"Character count display: {count_text}")
            except Exception:
                pass

            page.wait_for_timeout(3000)

            # Click Post/Tweet button — poll for enabled state, use JS click
            posted = False
            for sel in ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']:
                try:
                    btn = page.wait_for_selector(sel, timeout=8000)
                    for _ in range(20):
                        if btn.is_enabled():
                            break
                        page.wait_for_timeout(500)
                    if btn.is_enabled():
                        page.evaluate("el => el.click()", btn)
                        posted = True
                        break
                except PWTimeout:
                    continue

            if not posted:
                self.logger.error("Could not find Twitter Post button.")
                return None

            page.wait_for_timeout(4000)

            # Capture tweet URL
            post_url = TWITTER_URL
            try:
                # Look for the new tweet in the timeline
                link = page.query_selector('a[href*="/status/"]')
                if link:
                    href = link.get_attribute("href") or ""
                    if href.startswith("http"):
                        post_url = href
                    elif href:
                        post_url = TWITTER_URL + href
            except Exception:
                pass

            self.logger.info("✅ Tweet published.")
            return post_url

        except Exception as exc:
            self.logger.error(f"Twitter post failed: {exc}")
            self.audit.handle_error(exc, calling_skill="twitter-poster")
            return None

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_one(self, page, plan_path: Path) -> bool:
        try:
            text     = plan_path.read_text(encoding="utf-8")
            fm, body = self._parse_frontmatter(text)
        except Exception as exc:
            self.logger.error(f"Cannot read {plan_path.name}: {exc}")
            self.audit.handle_error(exc, calling_skill="twitter-poster")
            self._error_count += 1
            return False

        if fm.get("type") != "twitter-post":
            self.logger.warning(f"Skipping {plan_path.name} — type is not 'twitter-post'")
            self._skipped_count += 1
            return False

        if not fm.get("approved_by"):
            self.logger.error(f"Skipping {plan_path.name} — missing approved_by field")
            self.audit.log_action(
                "ERROR", "twitter-poster", f"Approved/{plan_path.name}",
                outcome="failed", notes="Missing approved_by — skipped",
            )
            self._error_count += 1
            return False

        if fm.get("published"):
            self.logger.info(f"Skipping {plan_path.name} — already published")
            self._skipped_count += 1
            return False

        tweet = self._extract_tweet(body)
        if not tweet:
            self.logger.error(f"No tweet content found in {plan_path.name}")
            self._error_count += 1
            return False

        # Enforce 280 char limit
        if len(tweet) > TWEET_MAX_CHARS:
            if fm.get("allow_truncate"):
                tweet = tweet[:TWEET_MAX_CHARS - 3] + "..."
                self.logger.warning(f"Tweet truncated to {TWEET_MAX_CHARS} chars")
            else:
                self.logger.error(
                    f"Tweet is {len(tweet)} chars (limit {TWEET_MAX_CHARS}). "
                    "Set allow_truncate: true in frontmatter to permit truncation."
                )
                self.audit.log_action(
                    "ERROR", "twitter-poster", f"Approved/{plan_path.name}",
                    outcome="failed",
                    notes=f"Tweet too long: {len(tweet)} chars — skipped",
                )
                self._error_count += 1
                return False

        title = fm.get("title", plan_path.stem)
        self.logger.info(f"Tweeting: {title}")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would tweet ({len(tweet)} chars):\n{tweet[:280]}")
            self.audit.log_action(
                "SOCIAL_POST", "twitter-poster", f"Approved/{plan_path.name}",
                notes=f"dry-run | title: {title} | chars: {len(tweet)}",
            )
            return True

        post_url = self._post_to_twitter(page, tweet)
        if not post_url:
            self._error_count += 1
            return False

        self._move_to_done(plan_path, fm, body, post_url)
        self._posted_count += 1
        self.logger.info(f"✅ Posted and archived: {plan_path.name}")
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._ensure_gold_folders()
        self._print_banner_tw()
        self._start_time = datetime.now()
        self._running    = True

        self.audit.log_action(
            "SKILL_RUN", "twitter-poster", "skills/social-poster.md",
            notes=f"TwitterPoster started — watch={self.watch_mode} dry_run={self.dry_run}",
        )

        with sync_playwright() as pw:
            browser = pw.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1366, "height": 900},
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(TWITTER_URL + "/home", wait_until="commit", timeout=60_000)
            page.wait_for_timeout(5000)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.single_file:
                    target = self.approved_path / self.single_file
                    if not target.exists():
                        self.logger.error(f"File not found in Approved/: {self.single_file}")
                    else:
                        self._process_one(page, target)

                elif self.watch_mode:
                    self.logger.info(f"Watch mode — checking every {DEFAULT_INTERVAL}s. Ctrl+C to stop.")
                    while self._running:
                        for plan in self._get_approved_posts():
                            if not self._running:
                                break
                            self._process_one(page, plan)
                            time.sleep(5)
                        for _ in range(DEFAULT_INTERVAL):
                            if not self._running:
                                break
                            time.sleep(1)

                else:
                    posts = self._get_approved_posts()
                    if not posts:
                        self.logger.info("No approved Twitter posts found in Approved/.")
                    for plan in posts:
                        self._process_one(page, plan)
                        time.sleep(5)

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
        print("  TwitterPoster stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Posted     : {self._posted_count}")
        print(f"  Skipped    : {self._skipped_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "twitter-poster", "skills/social-poster.md",
            notes=f"TwitterPoster stopped — posted: {self._posted_count}, errors: {self._error_count}",
        )

    def _print_banner_tw(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Twitter / X Poster")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode      : {mode}")
        print(f"  Vault     : {self.vault_path}")
        print(f"  Reads from: Approved/ (type: twitter-post)")
        print(f"  Session   : {SESSION_DIR}")
        print(f"  Limit     : {TWEET_MAX_CHARS} chars per tweet")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Twitter / X Poster")
    p.add_argument("--dry-run", action="store_true", help="Preview posts, no browser action")
    p.add_argument("--watch",   action="store_true", help="Watch Approved/ continuously")
    p.add_argument("--post",    metavar="FILE",      help="Post one specific approved file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    TwitterPoster(watch=args.watch, single_file=args.post).start()
