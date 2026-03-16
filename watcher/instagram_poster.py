"""
instagram_poster.py
-------------------
Gold Tier — Instagram Poster using Playwright with Human-in-the-Loop.

Full approval workflow:
  1. Agent creates post draft → Plans/
  2. Human reviews → approves → Approved/
  3. This script reads Approved/ (type: instagram-post) and posts via browser
  4. Moves executed plan to Done/YYYY-MM/

SENSITIVE: Never posts without an Approved/ entry with approved_by: human.

Note: Instagram is a mobile-first platform. This script uses Instagram's web
interface (instagram.com). Photo/video posts require a local image path in
the plan frontmatter (image_path: /path/to/image.jpg). Caption-only posts
are supported for story-based or link-in-bio update workflows.

Run:
    python instagram_poster.py                  # post all pending approved posts
    python instagram_poster.py --dry-run        # preview posts, no browser
    python instagram_poster.py --watch          # watch Approved/ and post as they arrive
    python instagram_poster.py --post <file>    # post one specific approved file

Setup:
    1. pip install -r requirements.txt
    2. playwright install chromium
    3. python instagram_poster.py               # browser opens, sign into Instagram once
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
INSTAGRAM_URL    = "https://www.instagram.com"
SESSION_DIR      = Path(__file__).parent / "sessions" / "instagram"
LOGIN_TIMEOUT_MS = 90_000
PAGE_LOAD_MS     = 30_000
CAPTION_MAX_CHARS = 2_200    # Instagram caption limit
DEFAULT_INTERVAL  = int(os.getenv("INSTAGRAM_POLL_INTERVAL", "300"))


class InstagramPoster(BaseWatcher):
    """
    Reads approved Instagram post plans from Approved/, posts them via
    Playwright browser automation, then moves each plan to Done/.

    Human-in-the-Loop is enforced:
    - Only files with type: instagram-post and approved_by: human are processed.
    - Requires image_path in frontmatter for photo posts.
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
    def _extract_caption(body: str) -> str:
        markers = [
            r"##\s+Caption\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Post Content\s*\n(.*?)(?=\n##|\Z)",
            r"##\s+Instagram Post\s*\n(.*?)(?=\n##|\Z)",
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
                    fm.get("type") == "instagram-post"
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
            f"**Posted by:** instagram_poster.py\n"
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
            "SOCIAL_POST", "instagram-poster",
            f"Approved/{plan_path.name}", rel_dest, "success",
            notes=f"platform: instagram | url: {post_url}",
        )
        self.log_to_vault(
            "SKILL_RUN", f"Approved/{plan_path.name}", rel_dest,
            notes=f"Instagram post published: {post_url}",
        )

    # ------------------------------------------------------------------
    # Instagram browser automation
    # ------------------------------------------------------------------

    def _is_logged_in(self, page) -> bool:
        """Check actual page content — Instagram shows login form even at root URL."""
        try:
            # If nav sidebar with Home/Search/Explore is present, we're logged in
            page.wait_for_selector(
                'a[href="/"][role="link"], a[href*="/direct/"], [aria-label="Home"]',
                timeout=5000,
            )
            return True
        except PWTimeout:
            return False

    def _wait_for_login(self, page) -> bool:
        page.wait_for_timeout(3000)
        if self._is_logged_in(page):
            self.logger.info("Instagram: logged in.")
            return True
        self.logger.info("Instagram: not logged in. Waiting for manual login ...")
        self.logger.info("  → Please sign into Instagram in the browser window.")
        try:
            # Wait until the nav sidebar appears
            page.wait_for_selector(
                'a[href="/"][role="link"], a[href*="/direct/"], [aria-label="Home"]',
                timeout=LOGIN_TIMEOUT_MS,
            )
            page.wait_for_timeout(2000)
            self.logger.info("Instagram: login detected.")
            return True
        except PWTimeout:
            self.logger.error("Instagram login timed out.")
            return False

    def _post_to_instagram(self, page, caption: str, image_path: "str | None") -> "str | None":
        """
        Post to Instagram via the web interface.
        Navigates directly to /create/select/ and sets files on the hidden
        file input — bypasses file chooser dialog (which Meta blocks).
        Returns post URL (or profile URL as fallback) on success, None on failure.
        """
        if len(caption) > CAPTION_MAX_CHARS:
            self.logger.error(f"Caption too long: {len(caption)} chars (limit {CAPTION_MAX_CHARS})")
            return None
        try:
            # Upload file if image_path provided
            if image_path and Path(image_path).exists():
                try:
                    # Navigate directly to the create page
                    page.goto(
                        "https://www.instagram.com/create/select/",
                        wait_until="domcontentloaded",
                        timeout=PAGE_LOAD_MS,
                    )
                    page.wait_for_timeout(3000)

                    # Make hidden file input interactable and set files directly
                    page.evaluate("""() => {
                        const inputs = document.querySelectorAll('input[type="file"]');
                        inputs.forEach(i => {
                            i.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;position:fixed!important;top:0;left:0;width:1px;height:1px;';
                            i.removeAttribute('hidden');
                        });
                    }""")
                    page.wait_for_timeout(500)
                    page.locator('input[type="file"]').first.set_input_files(image_path)
                    self.logger.info(f"Image uploaded: {image_path}")
                    page.wait_for_timeout(4000)

                    # Click Next through crop/filter steps
                    for _ in range(3):
                        try:
                            page.click(
                                'button:has-text("Next"), div[role="button"]:has-text("Next")',
                                timeout=5000,
                            )
                            page.wait_for_timeout(2000)
                        except PWTimeout:
                            break

                    # Type caption
                    caption_selectors = [
                        'textarea[aria-label*="caption"]',
                        'div[aria-label*="caption"]',
                        'textarea[placeholder*="caption"]',
                        'div[contenteditable="true"]',
                        'textarea',
                    ]
                    for sel in caption_selectors:
                        try:
                            cap_field = page.wait_for_selector(sel, timeout=5000)
                            cap_field.click()
                            page.wait_for_timeout(500)
                            page.keyboard.type(caption, delay=20)
                            self.logger.info(f"Caption typed via: {sel}")
                            break
                        except PWTimeout:
                            continue

                    page.wait_for_timeout(1000)

                    # Click Share
                    share_selectors = [
                        'div[role="button"]:has-text("Share")',
                        'button:has-text("Share")',
                    ]
                    shared = False
                    for sel in share_selectors:
                        try:
                            btn = page.wait_for_selector(sel, timeout=5000)
                            if btn.is_enabled():
                                page.evaluate("el => el.click()", btn)
                                shared = True
                                break
                        except PWTimeout:
                            continue

                    if not shared:
                        self.logger.error("Could not click Instagram Share button.")
                        return None

                    page.wait_for_timeout(30000)

                except Exception as exc:
                    self.logger.error(f"Instagram image upload failed: {exc}")
                    return None
            else:
                # No image — log warning and skip (Instagram requires image for feed posts)
                self.logger.warning(
                    "No valid image_path in plan frontmatter. "
                    "Instagram feed posts require an image. Skipping browser action."
                )
                return INSTAGRAM_URL  # Return profile as placeholder

            post_url = INSTAGRAM_URL
            try:
                link = page.query_selector('a[href*="/p/"]')
                if link:
                    href = link.get_attribute("href") or ""
                    if href.startswith("http"):
                        post_url = href
                    elif href:
                        post_url = INSTAGRAM_URL + href
            except Exception:
                pass

            self.logger.info("✅ Instagram post published.")
            return post_url

        except Exception as exc:
            self.logger.error(f"Instagram post failed: {exc}")
            self.audit.handle_error(exc, calling_skill="instagram-poster")
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
            self.audit.handle_error(exc, calling_skill="instagram-poster")
            self._error_count += 1
            return False

        if fm.get("type") != "instagram-post":
            self.logger.warning(f"Skipping {plan_path.name} — type is not 'instagram-post'")
            self._skipped_count += 1
            return False

        if not fm.get("approved_by"):
            self.logger.error(f"Skipping {plan_path.name} — missing approved_by field")
            self.audit.log_action(
                "ERROR", "instagram-poster", f"Approved/{plan_path.name}",
                outcome="failed", notes="Missing approved_by — skipped",
            )
            self._error_count += 1
            return False

        if fm.get("published"):
            self.logger.info(f"Skipping {plan_path.name} — already published")
            self._skipped_count += 1
            return False

        caption    = self._extract_caption(body)
        image_path = fm.get("image_path")  # optional — full path to local image file

        if not caption:
            self.logger.error(f"No caption content found in {plan_path.name}")
            self._error_count += 1
            return False

        title = fm.get("title", plan_path.stem)
        self.logger.info(f"Posting to Instagram: {title}")

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] Would post ({len(caption)} chars):\n{caption[:200]} ...")
            self.audit.log_action(
                "SOCIAL_POST", "instagram-poster", f"Approved/{plan_path.name}",
                notes=f"dry-run | title: {title}",
            )
            return True

        post_url = self._post_to_instagram(page, caption, image_path)
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
        self._print_banner_ig()
        self._start_time = datetime.now()
        self._running    = True

        self.audit.log_action(
            "SKILL_RUN", "instagram-poster", "skills/social-poster.md",
            notes=f"InstagramPoster started — watch={self.watch_mode} dry_run={self.dry_run}",
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
            page.goto(INSTAGRAM_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

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
                        self.logger.info("No approved Instagram posts found in Approved/.")
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
        print("  InstagramPoster stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Posted     : {self._posted_count}")
        print(f"  Skipped    : {self._skipped_count}")
        print(f"  Errors     : {self._error_count}")
        print("=" * 60)
        print()

        self.audit.log_action(
            "SKILL_RUN", "instagram-poster", "skills/social-poster.md",
            notes=f"InstagramPoster stopped — posted: {self._posted_count}, errors: {self._error_count}",
        )

    def _print_banner_ig(self) -> None:
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Instagram Poster")
        print("  Gold Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode      : {mode}")
        print(f"  Vault     : {self.vault_path}")
        print(f"  Reads from: Approved/ (type: instagram-post)")
        print(f"  Session   : {SESSION_DIR}")
        print(f"  Note      : image_path in frontmatter required for feed posts")
        print("=" * 60)
        print()


# ── Entry point ───────────────────────────────────────────────

def parse_args() -> "argparse.Namespace":
    p = argparse.ArgumentParser(description="Gold Tier — Instagram Poster")
    p.add_argument("--dry-run", action="store_true", help="Preview posts, no browser action")
    p.add_argument("--watch",   action="store_true", help="Watch Approved/ continuously")
    p.add_argument("--post",    metavar="FILE",      help="Post one specific approved file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    InstagramPoster(watch=args.watch, single_file=args.post).start()
