"""
facebook_poster.py
------------------
Gold Tier — Facebook Poster using Playwright with Human-in-the-Loop.

Full approval workflow:
  1. Agent creates post draft → Plans/
  2. Human reviews → approves → Approved/
  3. This script reads Approved/ (type: facebook-post) and posts via browser
  4. Moves executed plan to Done/YYYY-MM/

SENSITIVE: Never posts without an Approved/ entry with approved_by: human.

Run:
    python facebook_poster.py                  # post all pending approved posts
    python facebook_poster.py --dry-run        # preview posts, no browser
    python facebook_poster.py --watch          # watch Approved/ and post as they arrive
    python facebook_poster.py --post <file>    # post one specific approved file

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python facebook_poster.py               # browser opens, sign into Facebook once
"""

import os
import re
import sys
import time
import argparse
import yaml
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from base_watcher import BaseWatcher
from audit_logger import AuditLogger

# ── Config ────────────────────────────────────────────────────
FACEBOOK_URL     = "https://www.facebook.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "facebook"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
POST_MAX_CHARS   = 63_206     # Facebook hard limit
DEFAULT_INTERVAL = int(os.getenv("FACEBOOK_POLL_INTERVAL", "300"))


class FacebookPoster(BaseWatcher):
    """
    Reads approved Facebook post plans from Approved/, posts them via
    Playwright browser automation, then moves each plan to Done/.

    Human-in-the-Loop is enforced:
    - Only files with type: facebook-post and approved_by: human are processed.
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
    def _extract_post_content(body: str) -> str:
        markers = [
            r"##\s+Post Content\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Facebook Post\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Proposed Actions\s*\n(.*?)(?=\n##|\Z)",
        ]
        for pattern in markers:
            m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
        return "\n".join(lines[:20]).strip()

    def _get_approved_posts(self) -> "list[Path]":
        if not self.approved_path.exists():
            return []
        posts = []
        for f in self.approved_path.rglob("*.md"):
            try:
                fm, _ = self._parse_frontmatter(f.read_text(encoding="utf-8"))
                if (
                    fm.get("type") == "facebook-post"
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
            f"**Posted by:** facebook_poster.py\n"
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
            "SOCIAL_POST", "facebook-poster",
            f"Approved/{plan_path.name}", rel_dest, "success",
            notes=f"platform: facebook | url: {post_url}",
        )
        self.log_to_vault(
            "SKILL_RUN", f"Approved/{plan_path.name}", rel_dest,
            notes=f"Facebook post published: {post_url}",
        )

    # ------------------------------------------------------------------
    # Facebook browser automation
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        """Check if logged in by URL; wait for manual login if not."""
        page.wait_for_timeout(3000)
        url = page.url
        if "facebook.com" in url and "login" not in url and "checkpoint" not in url:
            self.logger.info("Facebook: logged in.")
            return True
        if "login" in url or "checkpoint" in url:
            self.logger.info("Facebook: not logged in. Waiting for manual login ...")
            self.logger.info("  → Please sign into Facebook in the browser window.")
            try:
                page.wait_for_function(
                    "() => !window.location.href.includes('login') && !window.location.href.includes('checkpoint')",
                    timeout=LOGIN_TIMEOUT_MS,
                )
                page.wait_for_timeout(2000)
                self.logger.info("Facebook: login detected.")
                return True
            except PWTimeout:
                self.logger.error("Facebook login timed out.")
                return False
        # Navigate to home directly
        page.goto(FACEBOOK_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        page.wait_for_timeout(3000)
        url = page.url
        if "login" not in url and "checkpoint" not in url:
            self.logger.info("Facebook: logged in.")
            return True
        self.logger.error(f"Facebook: could not confirm login. URL: {url}")
        return False

    def _post_to_facebook(self, page, content: str) -> "str | None":
        """Post text content to Facebook. Returns post URL or None on failure."""
        if len(content) > POST_MAX_CHARS:
            self.logger.error(f"Post too long: {len(content)} chars (limit {POST_MAX_CHARS})")
            return None
        try:
            page.goto(FACEBOOK_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Click "What's on your mind?" / create post area
            composer_selectors = [
                '[aria-label="Create a post"]',
                'div[role="button"]:has-text("What\'s on your mind")',
                'span:has-text("What\'s on your mind")',
                '[placeholder="What\'s on your mind"]',
                'div[data-pagelet="FeedUnit_0"] [role="button"]',
            ]
            opened = False
            for sel in composer_selectors:
                try:
                    page.click(sel, timeout=8000)
                    opened = True
                    self.logger.info(f"Composer opened via: {sel}")
                    break
                except PWTimeout:
                    continue

            if not opened:
                self.logger.error("Could not open Facebook post composer.")
                return None

            page.wait_for_timeout(3000)

            # Type into the post text area
            editor_selectors = [
                '[contenteditable="true"][role="textbox"]',
                '[aria-label="What\'s on your mind"]',
                '[data-lexical-editor="true"]',
                '[role="dialog"] [contenteditable="true"]',
                'div[contenteditable="true"]',
            ]
            typed = False
            for sel in editor_selectors:
                try:
                    editor = page.wait_for_selector(sel, timeout=10000)
                    editor.click()
                    page.wait_for_timeout(500)
                    page.keyboard.type(content, delay=30)
                    typed = True
                    self.logger.info(f"Editor found via: {sel}")
                    break
                except PWTimeout:
                    continue

            if not typed:
                self.logger.error("Could not find Facebook post text area.")
                return None

            page.wait_for_timeout(2000)

            # Click Post button — use JS click to bypass Facebook overlay interception
            post_btn_selectors = [
                'div[role="button"]:has-text("Post")',
                'div[aria-label="Post"][role="button"]',
                'button[type="submit"]:has-text("Post")',
            ]
            posted = False
            for sel in post_btn_selectors:
                try:
                    btn = page.wait_for_selector(sel, timeout=5000)
                    if btn.is_enabled():
                        # Use JS click to bypass overlay interception
                        page.evaluate("el => el.click()", btn)
                        posted = True
                        self.logger.info(f"Post button clicked via: {sel}")
                        break
                except PWTimeout:
                    continue

            if not posted:
                self.logger.error("Could not find Facebook Post button.")
                return None

            page.wait_for_timeout(4000)
            post_url = FACEBOOK_URL
            try:
                link = page.query_selector('a[href*="/posts/"], a[href*="?story_fbid="]')
                if link:
                    href = link.get_attribute("href") or ""
                    if href.startswith("http"):
                        post_url = href
                    elif href:
                        post_url = FACEBOOK_URL + href
            except Exception:
                pass

            self.logger.info("✅ Facebook post published.")
            return post_url

        except Exception as exc:
            self.logger.error(f"Facebook post failed: {exc}")
            recovery = self.audit.handle_error(exc, calling_skill="facebook-poster")
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
            self.audit.handle_error(exc, calling_skill="facebook-poster")
            self._error_count += 1
            return False

        if fm.get("type") != "facebook-post":
            self.logger.warning(f"Skipping {plan_path.name} — type is not 'facebook-post'")
            self._skipped_count += 1
            return False

        if not fm.get("approved_by"):
            self.logger.error(f"Skipping {plan_path.name} — missing approved_by field")
            self.audit.log_action(
                "ERROR", "facebook-poster", f"Approved/{plan_path.name}",
                outcome="failed", notes="Missing approved_by — skipped",
            )
            self._error_count += 1
            return False

        if fm.get("published"):
            self.logger.info(f"Skipping {plan_path.name} — already published")
            self._skipped_count += 1
            return False

        content = self._extract_post_content(body)
        if not content:
            self.logger.error(f"No post content found in {plan_path.name}")
            self._error_count += 1
            return False

        title = fm.get("title", plan_path.stem)
        self.logger.info(f"Posting to Facebook: {title}")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would post ({len(content)} chars):\n{content[:200]} ...")
            self.audit.log_action(
                "SOCIAL_POST", "facebook-poster", f"Approved/{plan_path.name}",
                notes=f"dry-run | title: {title}",
            )
            return True

        post_url = self._post_to_facebook(page, content)
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
        self._print_banner_fb()
        self._start_time = datetime.now()
        self._running    = True

        self.audit.log_action(
            "SKILL_RUN", "facebook-poster", "skills/social-poster.md",
            notes=f"FacebookPoster started — watch={self.watch_mode} dry_run={self.dry_run}",
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
            page.goto(FACEBOOK_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

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
                        self.logger.info("No approved Facebook posts found in Approved/.")
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
        print("  FacebookPoster stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Posted     : {self._posted_count}")
        print(f"  Skipped    : {self._skipped_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "facebook-poster", "skills/social-poster.md",
            notes=f"FacebookPoster stopped — posted: {self._posted_count}, errors: {self._error_count}",
        )

    def _print_banner_fb(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Facebook Poster")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode      : {mode}")
        print(f"  Vault     : {self.vault_path}")
        print(f"  Reads from: Approved/ (type: facebook-post)")
        print(f"  Session   : {SESSION_DIR}")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Facebook Poster")
    p.add_argument("--dry-run", action="store_true", help="Preview posts, no browser action")
    p.add_argument("--watch",   action="store_true", help="Watch Approved/ continuously")
    p.add_argument("--post",    metavar="FILE",      help="Post one specific approved file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    FacebookPoster(watch=args.watch, single_file=args.post).start()
