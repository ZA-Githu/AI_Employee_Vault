"""
linkedin_poster.py
------------------
Silver Tier — LinkedIn Poster using Playwright with Human-in-the-Loop.

Full approval workflow:
  1. Agent creates post draft → Plans/
  2. Human reviews → approves → Approved/
  3. This script reads Approved/ and posts to LinkedIn via browser automation
  4. Moves executed plan to Done/YYYY-MM/

SENSITIVE: Never posts without an Approved/ entry with approved_by: human.

Run:
    python linkedin_poster.py                  # check Approved/, post all pending
    python linkedin_poster.py --dry-run        # preview posts, no browser action
    python linkedin_poster.py --watch          # watch Approved/ and post as they arrive
    python linkedin_poster.py --post <file>    # post one specific approved file

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python linkedin_poster.py               # browser opens, sign into LinkedIn once
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

# ── Config ────────────────────────────────────────────────────
LINKEDIN_URL     = "https://www.linkedin.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "linkedin"
LOGIN_TIMEOUT_MS = 60_000
PAGE_LOAD_MS     = 30_000
POST_MAX_CHARS   = 3000      # LinkedIn hard limit
DEFAULT_INTERVAL = int(os.getenv("LINKEDIN_POLL_INTERVAL", "300"))


class LinkedInPoster(BaseWatcher):
    """
    Reads approved LinkedIn post plans from Approved/, posts them via
    Playwright browser automation, then moves each plan to Done/.

    Human-in-the-Loop is enforced at the read stage:
    - Only files in Approved/ with approved_by: human are processed.
    - Plans without this field are logged as ERROR and skipped.
    """

    def __init__(self, watch: bool = False, single_file: str | None = None):
        super().__init__()
        self.watch_mode       = watch
        self.single_file      = single_file
        self._running         = False
        self._posted_count    = 0
        self._skipped_count   = 0
        self._error_count     = 0
        self._start_time: datetime | None = None

        # Silver Tier paths
        self.approved_path  = self.vault_path / "Approved"
        self.done_path      = self.vault_path / "Done"
        self.plans_path     = self.vault_path / "Plans"
        self.pending_path   = self.vault_path / "Pending_Approval"

        SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Vault helpers
    # ------------------------------------------------------------------

    def _ensure_silver_folders(self) -> None:
        for folder in [self.approved_path, self.done_path, self.plans_path, self.pending_path]:
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        """
        Split a .md file into (frontmatter_dict, body_text).
        Returns ({}, text) if no YAML frontmatter found.
        """
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
        """
        Extract the actual post text from the plan body.
        Looks for content under '## Post Content', '## Proposed Actions',
        or '## LinkedIn Post', falling back to the full body excerpt.
        """
        markers = [
            r"##\s+Post Content\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+LinkedIn Post\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Proposed Actions\s*\n(.*?)(?=\n##|\Z)",
        ]
        for pattern in markers:
            m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        # Fallback: first non-header paragraph
        lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
        return "\n".join(lines[:20]).strip()

    def _get_approved_posts(self) -> list[Path]:
        """Return approved LinkedIn post plans sorted by priority then date."""
        if not self.approved_path.exists():
            return []
        files = list(self.approved_path.rglob("*.md"))
        posts = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = self._parse_frontmatter(text)
                if (
                    fm.get("type") == "linkedin-post"
                    and fm.get("approved_by")
                    and fm.get("status") == "approved"
                    and not fm.get("published")           # skip already-published
                ):
                    posts.append(f)
            except Exception:
                continue

        # Sort: critical > high > medium > low
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        posts.sort(key=lambda f: priority_order.get(
            self._parse_frontmatter(f.read_text(encoding="utf-8"))[0].get("priority", "medium"), 2
        ))
        return posts

    def _move_to_done(self, plan_path: Path, fm: dict, body: str, post_url: str) -> None:
        """Stamp the plan as published and move it to Done/YYYY-MM/."""
        today      = datetime.now().strftime("%Y-%m-%d")
        month_dir  = self.done_path / datetime.now().strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        fm["status"]    = "published"
        fm["published"] = today
        fm["post_url"]  = post_url

        fm_lines = "\n".join(f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {v}" for k, v in fm.items())
        completion = (
            f"\n\n---\n## Completion Summary\n\n"
            f"**Posted by:** linkedin_poster.py\n"
            f"**Date:** {today}\n"
            f"**Post URL:** {post_url}\n"
        )
        new_content = f"---\n{fm_lines}\n---\n\n{body}{completion}"

        dest = month_dir / plan_path.name
        if not self.dry_run:
            dest.write_text(new_content, encoding="utf-8")
            plan_path.unlink()

        self.log_to_vault(
            "SKILL_RUN",
            f"Approved/{plan_path.name}",
            f"Done/{month_dir.name}/{plan_path.name}",
            notes=f"LinkedIn post published: {post_url}",
        )

    # ------------------------------------------------------------------
    # LinkedIn browser automation
    # ------------------------------------------------------------------

    def _wait_for_login(self, page) -> bool:
        """Check if logged in by URL; if not, wait for user to log in manually."""
        page.wait_for_timeout(3000)

        # If we're on the feed, we're logged in
        if "/feed" in page.url or "/in/" in page.url or "linkedin.com/home" in page.url:
            self.logger.info("LinkedIn: logged in.")
            return True

        # If redirected to login/signup page, wait for manual login
        if "login" in page.url or "signup" in page.url or "authwall" in page.url:
            self.logger.info("LinkedIn: not logged in. Waiting for manual login ...")
            self.logger.info("  → Please sign into LinkedIn in the browser window.")
            try:
                page.wait_for_url("**/feed/**", timeout=LOGIN_TIMEOUT_MS)
                self.logger.info("LinkedIn: login detected.")
                return True
            except PWTimeout:
                self.logger.error("LinkedIn login timed out.")
                return False

        # Unknown page — try navigating to feed directly
        self.logger.info(f"LinkedIn: on unknown page ({page.url}), navigating to feed...")
        page.goto(LINKEDIN_URL + "/feed/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        page.wait_for_timeout(3000)
        if "/feed" in page.url:
            self.logger.info("LinkedIn: logged in.")
            return True

        self.logger.error(f"LinkedIn: could not confirm login. Current URL: {page.url}")
        return False

    def _post_to_linkedin(self, page, content: str) -> str | None:
        """
        Automate the LinkedIn post creation flow.
        Returns the post URL on success, None on failure.
        """
        if len(content) > POST_MAX_CHARS:
            self.logger.error(f"Post too long: {len(content)} chars (limit {POST_MAX_CHARS})")
            return None

        try:
            # Navigate to feed
            page.goto(LINKEDIN_URL + "/feed/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
            page.wait_for_timeout(2000)

            # Click "Start a post" / share box
            # LinkedIn keeps changing these selectors; try all known variants
            share_triggers = [
                '.share-box-feed-entry__trigger',
                '[data-control-name="share.sharebox_text"]',
                'button:has-text("Start a post")',
                '.share-creation-state__placeholder',
                'button[aria-label="Start a post"]',
                '.artdeco-card button:has-text("Start a post")',
                # New 2024/2025 LinkedIn feed layout
                '[data-view-name="share-entry-point"]',
                'div.share-box-feed-entry__top-bar button',
            ]
            triggered = False
            for sel in share_triggers:
                try:
                    page.click(sel, timeout=5000)
                    triggered = True
                    self.logger.info(f"Share box opened via: {sel}")
                    break
                except PWTimeout:
                    continue

            if not triggered:
                self.logger.error("Could not open LinkedIn post composer.")
                return None

            page.wait_for_timeout(2000)

            # Type content into the post editor
            # IMPORTANT: LinkedIn uses Quill.js (contenteditable). .fill() does NOT
            # trigger the input events LinkedIn listens for, so the Post button stays
            # disabled. We must use keyboard.type() to simulate real keystrokes.
            editor_selectors = [
                '.ql-editor[contenteditable="true"]',
                '[data-testid="ql-editor"]',
                '[aria-label="Text editor for creating content"]',
                '.editor-content [contenteditable="true"]',
                '[contenteditable="true"]',
            ]
            typed = False
            for sel in editor_selectors:
                try:
                    editor = page.wait_for_selector(sel, timeout=5000)
                    editor.click()
                    page.wait_for_timeout(800)
                    # Use keyboard.type() — fires proper input events that LinkedIn needs
                    page.keyboard.type(content, delay=20)
                    typed = True
                    break
                except PWTimeout:
                    continue

            if not typed:
                self.logger.error("Could not find LinkedIn post editor.")
                return None

            # Wait for LinkedIn to register the content and enable Post button
            page.wait_for_timeout(2000)

            # Click Post button — wait for it to become enabled after typing
            post_btn_selectors = [
                'button.share-actions__primary-action',
                'button[data-control-name="share.post"]',
                '.share-box_actions button.artdeco-button--primary',
                'div.share-box_actions button.artdeco-button--primary',
                'button:has-text("Post")',
                '[aria-label="Post"]',
            ]
            posted = False
            for sel in post_btn_selectors:
                try:
                    # Wait up to 8s for button to appear and become enabled
                    btn = page.wait_for_selector(sel, timeout=8000)
                    # Poll up to 5s for it to become enabled
                    for _ in range(10):
                        if btn.is_enabled():
                            break
                        page.wait_for_timeout(500)
                    if btn.is_enabled():
                        btn.click()
                        posted = True
                        break
                    else:
                        self.logger.warning(f"Post button found but still disabled: {sel}")
                except PWTimeout:
                    continue

            if not posted:
                self.logger.error("Could not find an enabled LinkedIn Post button.")
                return None

            # Wait for post confirmation / feed refresh
            page.wait_for_timeout(5000)

            # Try to capture the post URL from the success notification
            post_url = LINKEDIN_URL + "/feed/"
            try:
                link = page.query_selector('a[href*="/posts/"], a[href*="/activity-"]')
                if link:
                    post_url = link.get_attribute("href") or post_url
                    if not post_url.startswith("http"):
                        post_url = "https://www.linkedin.com" + post_url
            except Exception:
                pass

            self.logger.info(f"✅ LinkedIn post published.")
            return post_url

        except Exception as exc:
            self.logger.error(f"LinkedIn post failed: {exc}")
            self.log_to_vault("ERROR", "linkedin", notes=f"Post failed: {exc}", outcome="failed")
            return None

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def _process_one(self, page, plan_path: Path) -> bool:
        """Process a single approved LinkedIn post plan."""
        try:
            text     = plan_path.read_text(encoding="utf-8")
            fm, body = self._parse_frontmatter(text)
        except Exception as exc:
            self.logger.error(f"Cannot read {plan_path.name}: {exc}")
            self._error_count += 1
            return False

        # Hard approval gate
        if fm.get("type") != "linkedin-post":
            self.logger.warning(f"Skipping {plan_path.name} — type is not 'linkedin-post'")
            self._skipped_count += 1
            return False

        if not fm.get("approved_by"):
            self.logger.error(f"Skipping {plan_path.name} — missing approved_by field")
            self.log_to_vault("ERROR", f"Approved/{plan_path.name}", notes="Missing approved_by — skipped")
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
        self.logger.info(f"Posting: {title}")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would post ({len(content)} chars):\n{content[:200]} ...")
            self.log_to_vault(
                "SKILL_RUN",
                f"Approved/{plan_path.name}",
                notes=f"dry-run | title: {title}",
            )
            return True

        post_url = self._post_to_linkedin(page, content)
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
        self._ensure_silver_folders()
        self._print_li_banner()
        self._start_time = datetime.now()
        self._running    = True

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/linkedin-poster.md",
            notes=f"LinkedInPoster started — watch={self.watch_mode} dry_run={self.dry_run}",
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
                    "--disable-infobars",
                ],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(LINKEDIN_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

            if not self._wait_for_login(page):
                browser.close()
                self.stop()
                return

            try:
                if self.single_file:
                    # Post one specific file
                    target = self.approved_path / self.single_file
                    if not target.exists():
                        self.logger.error(f"File not found in Approved/: {self.single_file}")
                    else:
                        self._process_one(page, target)

                elif self.watch_mode:
                    self.logger.info(f"Watch mode — checking every {DEFAULT_INTERVAL}s. Ctrl+C to stop.\n")
                    while self._running:
                        for plan in self._get_approved_posts():
                            if not self._running:
                                break
                            self._process_one(page, plan)
                            time.sleep(5)   # brief pause between posts
                        for _ in range(DEFAULT_INTERVAL):
                            if not self._running:
                                break
                            time.sleep(1)

                else:
                    # Single pass — post all currently approved
                    posts = self._get_approved_posts()
                    if not posts:
                        self.logger.info("No approved LinkedIn posts found in Approved/.")
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
        print("  LinkedInPoster stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Posted     : {self._posted_count}")
        print(f"  Skipped    : {self._skipped_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/linkedin-poster.md",
            notes=f"LinkedInPoster stopped — posted: {self._posted_count}, errors: {self._error_count}",
        )

    def _print_li_banner(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — LinkedIn Poster")
        print("  Silver Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode      : {mode}")
        print(f"  Vault     : {self.vault_path}")
        print(f"  Reads from: Approved/ (type: linkedin-post)")
        print(f"  Session   : {SESSION_DIR}")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Silver Tier — LinkedIn Poster")
    p.add_argument("--dry-run", action="store_true", help="Preview posts, no browser action")
    p.add_argument("--watch",   action="store_true", help="Watch Approved/ continuously")
    p.add_argument("--post",    metavar="FILE",      help="Post one specific approved file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    LinkedInPoster(watch=args.watch, single_file=args.post).start()
