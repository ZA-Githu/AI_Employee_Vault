"""
social_media_executor_v2.py
---------------------------
Gold Tier — Social Media Manager Executor v2

Playwright-based executor for all 6 platforms with persistent sessions.
Platforms: Facebook, Instagram, LinkedIn, Twitter/X, WhatsApp, Gmail

Session storage: <vault_root>/session/<platform>/
  - Login once via: python social_media_executor_v2.py --login <platform>
  - Session saved permanently to disk (cookies, localStorage)
  - All subsequent runs: no manual login needed

Terminal usage:
  # First-time login (opens browser, wait for manual login, then press Enter):
  python social_media_executor_v2.py --login linkedin
  python social_media_executor_v2.py --login facebook
  python social_media_executor_v2.py --login instagram
  python social_media_executor_v2.py --login twitter
  python social_media_executor_v2.py --login whatsapp
  python social_media_executor_v2.py --login gmail

  # Execute a specific approved .md file:
  python social_media_executor_v2.py --execute Approved/POST_LinkedIn_123.md

  # Dry-run (validate file, print content, no browser):
  python social_media_executor_v2.py --execute Approved/POST_LinkedIn_123.md --dry-run

  # Execute all approved files for one platform:
  python social_media_executor_v2.py --platform linkedin

  # Execute all approved files across all platforms:
  python social_media_executor_v2.py --all

  # Check session status for all platforms:
  python social_media_executor_v2.py --check-session

  # Check session for one platform:
  python social_media_executor_v2.py --check-session --platform linkedin
"""

import os
import re
import sys
import time
import json
import yaml
import shutil
import argparse
import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# Ensure watcher/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))
from audit_logger import AuditLogger

# ── Windows UTF-8 output ───────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────
VAULT_PATH       = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
DRY_RUN          = os.getenv("DRY_RUN", "false").lower() == "true"

SESSION_ROOT     = VAULT_PATH / "session"
APPROVED_PATH    = VAULT_PATH / "Approved"
DONE_PATH        = VAULT_PATH / "Done"
LOGS_PATH        = VAULT_PATH / "Logs"
SCREENSHOTS_PATH = LOGS_PATH / "screenshots"
NEEDS_ACTION     = VAULT_PATH / "Needs_Action"

MAX_RETRIES      = 3
RETRY_DELAY_S    = 5        # seconds between retries
LOGIN_TIMEOUT_MS = 120_000  # 2 minutes for manual login
PAGE_LOAD_MS     = 30_000
ACTION_MS        = 10_000
POST_SETTLE_MS   = 4_000    # wait after clicking Post

PLATFORM_URLS = {
    "facebook":  "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin":  "https://www.linkedin.com",
    "twitter":   "https://x.com",
    "whatsapp":  "https://web.whatsapp.com",
    "gmail":     "https://mail.google.com",
}

CHAR_LIMITS = {
    "twitter":   280,
    "instagram": 2_200,
    "linkedin":  3_000,
    "facebook":  63_206,
    "whatsapp":  65_536,
    "gmail":     None,
}

SUPPORTED_PLATFORMS = list(PLATFORM_URLS.keys())

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SocialExecutorV2")


# ── Helpers ───────────────────────────────────────────────────

def parse_frontmatter(text: str) -> "tuple[dict, str]":
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


def write_frontmatter(fm: dict, body: str) -> str:
    lines = []
    for k, v in fm.items():
        if v is None or v == "":
            lines.append(f"{k}:")
        elif isinstance(v, bool):
            lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(i) for i in v)}]")
        else:
            safe = str(v).replace('"', "'")
            lines.append(f'{k}: "{safe}"')
    return f"---\n" + "\n".join(lines) + f"\n---\n\n{body}"


def extract_content(body: str) -> str:
    """Extract post content from ## Post Content section, falling back to body."""
    for pattern in [
        r"##\s+Post Content\s*\n(.*?)(?=\n##|\Z)",
        r"##\s+Tweet\s*\n(.*?)(?=\n##|\Z)",
        r"##\s+Caption\s*\n(.*?)(?=\n##|\Z)",
        r"##\s+Message\s*\n(.*?)(?=\n##|\Z)",
        r"##\s+Email Body\s*\n(.*?)(?=\n##|\Z)",
        r"##\s+Body\s*\n(.*?)(?=\n##|\Z)",
    ]:
        m = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Fallback: non-heading lines
    lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
    return "\n".join(lines[:30]).strip()


def take_screenshot(page, platform: str, slug: str) -> str:
    """Save screenshot to Logs/screenshots/. Returns relative path string."""
    SCREENSHOTS_PATH.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    name = f"{ts}-{platform}-{slug[:40]}.png"
    path = SCREENSHOTS_PATH / name
    try:
        page.screenshot(path=str(path))
        logger.info(f"Screenshot saved: Logs/screenshots/{name}")
    except Exception as e:
        logger.warning(f"Screenshot failed: {e}")
    return f"Logs/screenshots/{name}"


def move_to_done(plan_path: Path, fm: dict, body: str, post_url: str) -> Path:
    """Move approved file to Done/YYYY-MM/ with updated frontmatter."""
    today     = datetime.now().strftime("%Y-%m-%d")
    month_dir = DONE_PATH / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    fm["status"]    = "published"
    fm["published"] = today
    fm["post_url"]  = post_url

    dest = month_dir / plan_path.name
    dest.write_text(write_frontmatter(fm, body), encoding="utf-8")
    plan_path.unlink()
    return dest


def mark_failed(plan_path: Path, fm: dict, body: str, screenshot: str, error: str) -> None:
    """Update frontmatter in-place: status=failed, record screenshot path."""
    fm["status"]     = "failed"
    fm["failed_at"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    fm["screenshot"] = screenshot
    fm["error"]      = str(error)[:200]
    plan_path.write_text(write_frontmatter(fm, body), encoding="utf-8")


def get_approved_files(platform: "str | None" = None) -> "list[Path]":
    """Return approved .md files sorted by priority then mtime."""
    if not APPROVED_PATH.exists():
        return []
    files = []
    for f in APPROVED_PATH.glob("*.md"):
        try:
            fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
            if (
                fm.get("type") == "social-post"
                and fm.get("approved_by")
                and fm.get("status") == "approved"
                and not fm.get("published")
                and not fm.get("failed_at")
            ):
                if platform is None or fm.get("platform") == platform:
                    files.append(f)
        except Exception:
            continue
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    files.sort(key=lambda f: (
        priority_order.get(
            parse_frontmatter(f.read_text(encoding="utf-8"))[0].get("priority", "medium"), 2
        ),
        f.stat().st_mtime,
    ))
    return files


def validate_approval_gate(fm: dict, plan_path: Path) -> "str | None":
    """
    Return an error string if the gate fails, None if all clear.
    Gate conditions:
      1. type == social-post
      2. approved_by is non-empty
      3. status == approved
      4. platform is a supported platform
      5. published is not already set
    """
    if fm.get("type") != "social-post":
        return f"type is '{fm.get('type')}' — must be 'social-post'"
    if not fm.get("approved_by"):
        return "approved_by is empty — human approval required"
    if fm.get("status") != "approved":
        return f"status is '{fm.get('status')}' — must be 'approved'"
    if fm.get("platform") not in SUPPORTED_PLATFORMS:
        return f"platform '{fm.get('platform')}' is not supported (choose: {', '.join(SUPPORTED_PLATFORMS)})"
    if fm.get("published"):
        return f"already published on {fm.get('published')} — will not double-post"
    return None


def check_char_limit(content: str, platform: str, allow_truncate: bool) -> "tuple[str, bool]":
    """
    Returns (content, truncated).
    Raises ValueError if over limit and truncation not allowed.
    """
    limit = CHAR_LIMITS.get(platform)
    if limit is None:
        return content, False
    if len(content) <= limit:
        return content, False
    if allow_truncate:
        truncated = content[:limit - 3] + "..."
        logger.warning(f"Content truncated from {len(content)} to {limit} chars")
        return truncated, True
    raise ValueError(
        f"Content is {len(content)} chars — platform limit is {limit}. "
        f"Shorten the post or set allow_truncate: true in frontmatter."
    )


# ── Platform Posters ──────────────────────────────────────────

def post_facebook(page, content: str) -> str:
    """Post to Facebook feed. Returns post URL."""
    url = PLATFORM_URLS["facebook"]
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(2000)

    # Open composer
    for sel in [
        'div[role="button"]:has-text("What\'s on your mind")',
        '[aria-label="Create a post"]',
        'span:has-text("What\'s on your mind")',
        '[placeholder="What\'s on your mind"]',
    ]:
        try:
            page.click(sel, timeout=5000)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not open Facebook post composer")

    page.wait_for_timeout(2000)

    # Type content
    for sel in [
        '[contenteditable="true"][role="textbox"]',
        '[data-lexical-editor="true"]',
        'div[contenteditable="true"]',
        '[aria-label="What\'s on your mind"]',
    ]:
        try:
            ed = page.wait_for_selector(sel, timeout=5000)
            ed.click()
            page.wait_for_timeout(400)
            ed.type(content, delay=25)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Facebook text editor")

    page.wait_for_timeout(1500)

    # Click Post
    for sel in [
        'div[aria-label="Post"][role="button"]',
        'div[role="button"]:has-text("Post")',
        'button[type="submit"]:has-text("Post")',
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=5000)
            if btn.is_enabled():
                btn.click()
                break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Facebook Post button")

    page.wait_for_timeout(POST_SETTLE_MS)

    # Try to capture post URL
    try:
        link = page.query_selector('a[href*="/posts/"], a[href*="?story_fbid="]')
        if link:
            href = link.get_attribute("href") or ""
            return href if href.startswith("http") else url + href
    except Exception:
        pass
    return url


def post_linkedin(page, content: str) -> str:
    """Post to LinkedIn feed. Returns post URL."""
    url = PLATFORM_URLS["linkedin"]
    page.goto(url + "/feed/", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(5000)  # Wait for page to fully render

    # Click 'Start a post' - try multiple selector strategies
    clicked = False
    for sel in [
        'button:has-text("Start a post")',
        'div[role="button"]:has-text("Start a post")',
        '.share-box-feed-entry__trigger',
        'button.artdeco-button:has-text("Start a post")',
        '[aria-label="Start a post"]',
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=10000)
            if btn.is_visible():
                btn.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                btn.click()
                clicked = True
                break
        except PWTimeout:
            continue
    
    if not clicked:
        # Fallback: try to find by text content in any clickable element
        try:
            btn = page.wait_for_selector('text="Start a post"', timeout=5000)
            if btn.is_visible():
                btn.click()
                clicked = True
        except PWTimeout:
            pass
    
    if not clicked:
        raise RuntimeError("Could not find LinkedIn 'Start a post' button")

    page.wait_for_timeout(3000)

    # Wait for the composer modal to appear
    try:
        page.wait_for_selector('.UpdatesComposer, [aria-label*="Create a post"]', timeout=5000)
        logger.info("LinkedIn composer modal detected")
    except PWTimeout:
        logger.warning("Composer modal not detected, continuing anyway")

    page.wait_for_timeout(2000)

    # Fill editor - LinkedIn uses a contenteditable div
    # Try finding the editor with multiple strategies
    editor_found = False
    for sel in [
        'div.ql-editor[contenteditable="true"]',
        'div[contenteditable="true"][data-placeholder]',
        'div[role="textbox"][contenteditable="true"]',
        '.UpdatesComposer__editor',
        'div.ipsum-editor-textarea[contenteditable="true"]',
        '.composer-editor[contenteditable="true"]',
        'div[contenteditable="true"]',
    ]:
        try:
            ed = page.wait_for_selector(sel, timeout=5000)
            if ed.is_visible():
                logger.info(f"Found LinkedIn editor with selector: {sel}")
                ed.click()
                page.wait_for_timeout(800)
                # Clear any existing text first
                ed.press("Control+a")
                page.wait_for_timeout(200)
                ed.press("Delete")
                page.wait_for_timeout(200)
                # Type the content
                ed.type(content, delay=10)
                page.wait_for_timeout(500)
                # Verify content was entered
                text_content = ed.inner_text()
                logger.info(f"Editor text length after typing: {len(text_content)}")
                if len(text_content.strip()) > 0:
                    editor_found = True
                    break
                else:
                    logger.warning("Editor appears empty after typing, trying next selector...")
        except PWTimeout:
            continue
        except Exception as e:
            logger.warning(f"Editor attempt failed: {e}")
            continue
    
    if not editor_found:
        # Last resort: try keyboard-based approach
        logger.warning("Standard editor detection failed, trying keyboard fallback...")
        try:
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
            page.keyboard.press("Tab")
            page.wait_for_timeout(300)
            page.keyboard.type(content, delay=10)
            page.wait_for_timeout(500)
            logger.info("Keyboard fallback attempted")
            editor_found = True
        except Exception as e:
            logger.error(f"Keyboard fallback also failed: {e}")
            raise RuntimeError("Could not find LinkedIn post editor")

    page.wait_for_timeout(2000)

    # Click Post button
    post_clicked = False
    for sel in [
        'button:has-text("Post")',
        'button[aria-label="Post"]',
        '.share-actions__primary-action',
        'button.artdeco-button:has-text("Post")',
        'button:has-text("Now")',  # "Post now" variant
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=8000)
            if btn.is_visible() and btn.is_enabled():
                btn.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                btn.click()
                post_clicked = True
                break
        except PWTimeout:
            continue
    
    if not post_clicked:
        raise RuntimeError("Could not find LinkedIn Post button")

    page.wait_for_timeout(POST_SETTLE_MS)
    return url + "/feed/"


def post_instagram(page, content: str, image_path: "str | None") -> str:
    """Post to Instagram. image_path required for feed posts."""
    url = PLATFORM_URLS["instagram"]
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(2000)

    if not image_path or not Path(image_path).exists():
        logger.warning("Instagram: no valid image_path — skipping browser action")
        return url

    # Click Create / New post
    for sel in [
        '[aria-label="New post"]',
        'svg[aria-label="New post"]',
        '[aria-label="Create"]',
        'svg[aria-label="Create"]',
    ]:
        try:
            page.click(sel, timeout=5000)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Instagram Create button")

    page.wait_for_timeout(2000)

    # Upload image
    file_input = page.wait_for_selector('input[type="file"]', timeout=8000)
    file_input.set_input_files(str(image_path))
    page.wait_for_timeout(3000)

    # Navigate through crop / filter steps (up to 3 Next clicks)
    for _ in range(3):
        try:
            page.click(
                'button:has-text("Next"), div[role="button"]:has-text("Next")',
                timeout=5000,
            )
            page.wait_for_timeout(1500)
        except PWTimeout:
            break

    # Add caption
    for sel in [
        'textarea[aria-label*="caption" i]',
        'div[aria-label*="caption" i][contenteditable="true"]',
        'textarea[placeholder*="caption" i]',
        'div[contenteditable="true"]',
    ]:
        try:
            cap = page.wait_for_selector(sel, timeout=5000)
            cap.click()
            page.wait_for_timeout(400)
            cap.type(content, delay=20)
            break
        except PWTimeout:
            continue

    page.wait_for_timeout(1000)

    # Share
    for sel in ['button:has-text("Share")', 'div[role="button"]:has-text("Share")']:
        try:
            btn = page.wait_for_selector(sel, timeout=5000)
            if btn.is_enabled():
                btn.click()
                break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Instagram Share button")

    page.wait_for_timeout(POST_SETTLE_MS)

    try:
        link = page.query_selector('a[href*="/p/"]')
        if link:
            href = link.get_attribute("href") or ""
            return href if href.startswith("http") else url + href
    except Exception:
        pass
    return url


def post_twitter(page, content: str) -> str:
    """Post a tweet on X/Twitter. Returns tweet URL."""
    url = PLATFORM_URLS["twitter"]
    page.goto(url + "/home", wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(2000)

    # Open compose dialog
    composed = False
    for sel in [
        '[data-testid="SideNav_NewTweet_Button"]',
        'a[href="/compose/tweet"]',
        'div[aria-label="Post"][role="button"]',
    ]:
        try:
            page.click(sel, timeout=5000)
            composed = True
            break
        except PWTimeout:
            continue

    if not composed:
        try:
            page.click('[data-testid="tweetTextarea_0"]', timeout=5000)
            composed = True
        except PWTimeout:
            pass

    if not composed:
        raise RuntimeError("Could not open Twitter compose dialog")

    page.wait_for_timeout(1500)

    # Type tweet
    for sel in [
        '[data-testid="tweetTextarea_0"]',
        'div[role="textbox"][data-testid="tweetTextarea_0"]',
        'div[contenteditable="true"][role="textbox"]',
    ]:
        try:
            ed = page.wait_for_selector(sel, timeout=5000)
            ed.click()
            page.wait_for_timeout(400)
            ed.type(content, delay=25)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Twitter text area")

    page.wait_for_timeout(1000)

    # Post
    for sel in [
        '[data-testid="tweetButton"]',
        'div[data-testid="tweetButtonInline"]',
        'button[type="submit"]:has-text("Post")',
        'div[role="button"]:has-text("Post")',
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=5000)
            if btn.is_enabled():
                btn.click()
                break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Twitter Post button")

    page.wait_for_timeout(POST_SETTLE_MS)

    try:
        link = page.query_selector('a[href*="/status/"]')
        if link:
            href = link.get_attribute("href") or ""
            return href if href.startswith("http") else url + href
    except Exception:
        pass
    return url


def send_whatsapp(page, content: str, recipient: str) -> str:
    """Send WhatsApp message to recipient (phone number or contact name)."""
    url = PLATFORM_URLS["whatsapp"]
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(3000)

    # Search for contact
    for sel in [
        '[data-testid="chat-list-search"]',
        '[aria-label="Search input textbox"]',
        'div[role="textbox"][data-tab="3"]',
        '#side div[contenteditable="true"]',
    ]:
        try:
            search = page.wait_for_selector(sel, timeout=8000)
            search.click()
            page.wait_for_timeout(400)
            search.type(recipient, delay=50)
            page.wait_for_timeout(1500)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find WhatsApp search box")

    # Click first result
    for sel in [
        '[data-testid="cell-frame-container"]',
        'div[role="listitem"]',
        'li[data-testid="cell-frame-container"]',
    ]:
        try:
            result = page.wait_for_selector(sel, timeout=5000)
            result.click()
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError(f"Could not find WhatsApp contact: {recipient}")

    page.wait_for_timeout(1000)

    # Type message
    for sel in [
        '[data-testid="conversation-compose-box-input"]',
        'div[role="textbox"][data-tab="10"]',
        'div[contenteditable="true"][data-tab="10"]',
        'footer div[contenteditable="true"]',
    ]:
        try:
            msg_box = page.wait_for_selector(sel, timeout=5000)
            msg_box.click()
            page.wait_for_timeout(400)
            msg_box.type(content, delay=20)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find WhatsApp message input")

    page.wait_for_timeout(800)

    # Send
    for sel in [
        '[data-testid="send"]',
        'button[data-testid="send"]',
        'span[data-testid="send"]',
        'button[aria-label="Send"]',
    ]:
        try:
            page.click(sel, timeout=5000)
            break
        except PWTimeout:
            continue
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(2000)
    return url


def send_gmail(page, content: str, recipient: str, subject: str) -> str:
    """Send Gmail. Returns gmail URL."""
    url = PLATFORM_URLS["gmail"]
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    page.wait_for_timeout(2000)

    # Click Compose
    for sel in [
        '[gh="cm"]',
        'div[role="button"]:has-text("Compose")',
        '.T-I.T-I-KE',
        'button:has-text("Compose")',
    ]:
        try:
            page.click(sel, timeout=5000)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Gmail Compose button")

    page.wait_for_timeout(1500)

    # Fill To
    for sel in ['[name="to"]', 'input[aria-label="To"]', '[data-hm="to"] input']:
        try:
            to_field = page.wait_for_selector(sel, timeout=5000)
            to_field.click()
            to_field.type(recipient, delay=30)
            page.keyboard.press("Tab")
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Gmail To field")

    page.wait_for_timeout(400)

    # Fill Subject
    for sel in ['[name="subjectbox"]', 'input[aria-label="Subject"]', '[data-hm="subject"] input']:
        try:
            subj = page.wait_for_selector(sel, timeout=5000)
            subj.click()
            subj.type(subject or "(no subject)", delay=30)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Gmail Subject field")

    page.wait_for_timeout(400)

    # Fill Body
    for sel in [
        'div[role="textbox"][aria-label="Message Body"]',
        'div[contenteditable="true"][aria-label="Message Body"]',
        '.Am div[contenteditable="true"]',
        'div[aria-multiline="true"]',
    ]:
        try:
            body_field = page.wait_for_selector(sel, timeout=5000)
            body_field.click()
            body_field.type(content, delay=15)
            break
        except PWTimeout:
            continue
    else:
        raise RuntimeError("Could not find Gmail body field")

    page.wait_for_timeout(800)

    # Send
    for sel in [
        'div[role="button"][aria-label*="Send"]',
        '[data-tooltip*="Send"]',
        'div[aria-label="Send ‪(Ctrl-Enter)‬"]',
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=5000)
            btn.click()
            break
        except PWTimeout:
            continue
    else:
        page.keyboard.press("Control+Enter")

    page.wait_for_timeout(2000)
    return url


# ── Login once ────────────────────────────────────────────────

def do_login(platform: str) -> None:
    """
    Open browser with persistent session directory.
    Navigate to platform URL and wait for human to log in manually.
    Session is saved automatically when browser closes.
    """
    if platform not in SUPPORTED_PLATFORMS:
        print(f"[ERROR] Unknown platform: {platform}. Choose from: {', '.join(SUPPORTED_PLATFORMS)}")
        sys.exit(1)

    session_dir = SESSION_ROOT / platform
    session_dir.mkdir(parents=True, exist_ok=True)
    url = PLATFORM_URLS[platform]

    print()
    print("=" * 60)
    print(f"  Login Mode — {platform.upper()}")
    print("=" * 60)
    print(f"  Session: {session_dir}")
    print(f"  URL    : {url}")
    print()
    print("  A browser window will open.")
    print(f"  Log into {platform.upper()} in that window.")
    if platform == "whatsapp":
        print("  Scan the QR code with your phone.")
    print("  Once logged in, come back here and press ENTER.")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--no-sandbox"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

        input("  >>> Press ENTER after you have logged in ... ")

        print(f"  Session saved to: {session_dir}")
        browser.close()

    print()
    print(f"  Login complete. Run with --execute or --all to post.")
    print()


# ── Session check ─────────────────────────────────────────────

def check_sessions(platform: "str | None" = None) -> None:
    """Print session status for all or one platform."""
    platforms = [platform] if platform else SUPPORTED_PLATFORMS
    print()
    print("  Session Status")
    print("  " + "-" * 50)
    for p in platforms:
        d = SESSION_ROOT / p
        if not d.exists():
            status = "MISSING  — run: python social_media_executor_v2.py --login " + p
        else:
            files = list(d.rglob("*"))
            if not files:
                status = "EMPTY    — run: python social_media_executor_v2.py --login " + p
            else:
                status = f"OK ({len(files)} session files)"
        print(f"  {p:<12} {status}")
    print()


# ── Core executor ─────────────────────────────────────────────

class SocialExecutorV2:
    """
    Reads an approved .md file from Approved/, posts via Playwright,
    moves to Done/ on success, records screenshot on failure.
    """

    def __init__(self):
        self.audit = AuditLogger(VAULT_PATH)
        SCREENSHOTS_PATH.mkdir(parents=True, exist_ok=True)
        DONE_PATH.mkdir(parents=True, exist_ok=True)

    def _open_browser(self, platform: str) -> "tuple":
        """Open Playwright persistent context for the platform."""
        session_dir = SESSION_ROOT / platform
        session_dir.mkdir(parents=True, exist_ok=True)

        viewport = {"width": 375, "height": 812} if platform == "instagram" else {"width": 1280, "height": 900}
        user_agent = None
        if platform == "instagram":
            user_agent = (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                "Mobile/15E148 Safari/604.1"
            )

        pw = sync_playwright().start()
        kwargs   = dict(
            user_data_dir=str(session_dir),
            headless=False,
            viewport=viewport,
            args=["--no-sandbox"],
        )
        if user_agent:
            kwargs["user_agent"] = user_agent

        browser = pw.chromium.launch_persistent_context(**kwargs)
        page    = browser.pages[0] if browser.pages else browser.new_page()
        return pw, browser, page

    def _check_login(self, page, platform: str) -> bool:
        """
        Return True if already logged in.
        If not, wait LOGIN_TIMEOUT_MS for manual login.
        """
        login_indicators = {
            "facebook":  ['div[role="feed"]', '[aria-label="Create"]', '[data-testid="royal_blue_bar"]'],
            "instagram": ['nav[role="navigation"]', 'a[href="/direct/inbox/"]', '[aria-label="Home"]'],
            "linkedin":  ['.global-nav__me', '.feed-identity-module', 'a[data-link-to="me"]'],
            "twitter":   ['[data-testid="SideNav_NewTweet_Button"]', '[data-testid="primaryColumn"]'],
            "whatsapp":  ['[data-testid="chat-list"]', '#pane-side', 'div[aria-label="Chat list"]'],
            "gmail":     ['div[role="main"]', 'div[gh="tl"]', '[aria-label="Inbox"]'],
        }
        selectors = login_indicators.get(platform, [])
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                logger.info(f"{platform}: already logged in")
                return True
            except PWTimeout:
                continue

        logger.warning(f"{platform}: not logged in. Waiting {LOGIN_TIMEOUT_MS // 1000}s for manual login ...")
        logger.warning(f"  → Please log into {platform.upper()} in the browser window.")
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=LOGIN_TIMEOUT_MS)
                logger.info(f"{platform}: login detected")
                return True
            except PWTimeout:
                continue

        logger.error(f"{platform}: login timed out")
        return False

    def execute_file(self, plan_path: Path) -> bool:
        """
        Execute a single approved file.
        Returns True on success, False on failure.
        """
        # Read file
        try:
            text     = plan_path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
        except Exception as exc:
            logger.error(f"Cannot read {plan_path.name}: {exc}")
            return False

        # Approval gate
        gate_error = validate_approval_gate(fm, plan_path)
        if gate_error:
            logger.error(f"Approval gate FAILED — {gate_error}")
            self.audit.log_action(
                "ERROR", "social-executor-v2",
                f"Approved/{plan_path.name}", None, "failed",
                notes=f"gate: {gate_error}",
            )
            return False

        platform      = fm["platform"]
        content       = extract_content(body)
        allow_trunc   = bool(fm.get("allow_truncate", False))
        image_path    = fm.get("image_path") or None
        recipient     = str(fm.get("recipient", "") or "")
        subject       = str(fm.get("subject", "") or "(no subject)")

        if not content:
            logger.error(f"No post content found in {plan_path.name}")
            return False

        # Char limit
        try:
            content, truncated = check_char_limit(content, platform, allow_trunc)
        except ValueError as exc:
            logger.error(str(exc))
            self.audit.log_action(
                "ERROR", "social-executor-v2",
                f"Approved/{plan_path.name}", None, "failed",
                notes=str(exc)[:150],
            )
            return False

        # Platform-specific required fields
        if platform in ("whatsapp", "gmail") and not recipient:
            logger.error(f"{platform} requires 'recipient' in frontmatter")
            return False

        # Dry-run
        if DRY_RUN:
            logger.info(f"[DRY-RUN] Would post to {platform} ({len(content)} chars):")
            logger.info(content[:300])
            self.audit.log_action(
                "SKILL_RUN", "social-executor-v2",
                f"Approved/{plan_path.name}", None, "success",
                notes=f"dry-run | platform: {platform} | chars: {len(content)}",
            )
            return True

        logger.info(f"Executing: {plan_path.name} → {platform}")

        # Retry loop
        last_exc      = None
        screenshot    = ""
        for attempt in range(1, MAX_RETRIES + 1):
            pw = browser = page = None
            try:
                pw, browser, page = self._open_browser(platform)
                page.goto(PLATFORM_URLS[platform], wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)

                if not self._check_login(page, platform):
                    browser.close()
                    pw.stop()
                    raise RuntimeError(f"Login failed or timed out for {platform}")

                # Dispatch to platform handler
                if platform == "facebook":
                    post_url = post_facebook(page, content)
                elif platform == "linkedin":
                    post_url = post_linkedin(page, content)
                elif platform == "instagram":
                    post_url = post_instagram(page, content, image_path)
                elif platform == "twitter":
                    post_url = post_twitter(page, content)
                elif platform == "whatsapp":
                    post_url = send_whatsapp(page, content, recipient)
                elif platform == "gmail":
                    post_url = send_gmail(page, content, recipient, subject)
                else:
                    raise RuntimeError(f"Unhandled platform: {platform}")

                browser.close()
                pw.stop()

                # Success
                dest = move_to_done(plan_path, fm, body, post_url)
                logger.info(f"SUCCESS: {platform} post published")
                logger.info(f"  URL    : {post_url}")
                logger.info(f"  Archived: {dest.relative_to(VAULT_PATH)}")

                self.audit.log_action(
                    "SOCIAL_POST", "social-executor-v2",
                    f"Approved/{plan_path.name}",
                    f"Done/{dest.parent.name}/{dest.name}",
                    "success",
                    notes=f"platform: {platform} | url: {post_url}",
                )
                return True

            except Exception as exc:
                last_exc = exc
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed: {exc}")

                if page:
                    try:
                        slug       = re.sub(r"[^a-z0-9]+", "-", plan_path.stem.lower())[:30]
                        screenshot = take_screenshot(page, platform, f"attempt{attempt}-{slug}")
                    except Exception:
                        pass

                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass

                if attempt < MAX_RETRIES:
                    logger.info(f"Retrying in {RETRY_DELAY_S}s ...")
                    time.sleep(RETRY_DELAY_S)

        # All retries exhausted
        logger.error(f"FAILED after {MAX_RETRIES} attempts: {plan_path.name}")
        logger.error(f"  Error     : {last_exc}")
        if screenshot:
            logger.error(f"  Screenshot: {screenshot}")
        logger.error(f"  File stays in Approved/ — reset status to 'approved' to retry.")

        mark_failed(plan_path, fm, body, screenshot, str(last_exc))
        self.audit.log_action(
            "SOCIAL_POST", "social-executor-v2",
            f"Approved/{plan_path.name}", None, "failed",
            notes=f"platform: {platform} | attempts: {MAX_RETRIES} | screenshot: {screenshot}",
            error={"message": str(last_exc)[:200], "level": "L3", "recovery_action": "manual_retry"},
        )
        return False

    def execute_all(self, platform: "str | None" = None) -> None:
        """Execute all approved files, optionally filtered by platform."""
        files = get_approved_files(platform)
        if not files:
            logger.info(f"No approved posts found{' for ' + platform if platform else ''}.")
            return

        label = platform or "all platforms"
        logger.info(f"Queue: {len(files)} approved post(s) for {label}")
        success = failed = 0

        for f in files:
            ok = self.execute_file(f)
            if ok:
                success += 1
            else:
                failed += 1
            time.sleep(5)   # rate-limit protection between posts

        print()
        print("=" * 60)
        print(f"  Execution complete — {label}")
        print(f"  Published : {success}")
        print(f"  Failed    : {failed}")
        print("=" * 60)
        print()


# ── Banner ────────────────────────────────────────────────────

def print_banner(mode: str, target: str = "") -> None:
    mode_str = "DRY-RUN" if DRY_RUN else "LIVE"
    print()
    print("=" * 60)
    print("  AI Employee Vault — Social Media Executor v2")
    print("  Gold Tier | Social Manager Extension")
    print(f"  Mode   : {mode_str}")
    print(f"  Action : {mode}  {target}")
    print(f"  Vault  : {VAULT_PATH}")
    print(f"  Session: {SESSION_ROOT}")
    print("=" * 60)
    print()


# ── CLI ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Social Media Executor v2 — post approved .md files via Playwright",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--login",
        metavar="PLATFORM",
        help="Open browser for first-time login. Platform: " + " | ".join(SUPPORTED_PLATFORMS),
    )
    group.add_argument(
        "--execute",
        metavar="FILE",
        help="Execute one approved .md file (path relative to vault root or Approved/)",
    )
    group.add_argument(
        "--platform",
        metavar="PLATFORM",
        help="Execute all approved files for one platform",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Execute all approved files across all platforms",
    )
    group.add_argument(
        "--check-session",
        action="store_true",
        dest="check_session",
        help="Show session status for all platforms",
    )

    p.add_argument("--dry-run", action="store_true", help="Validate only, no browser")
    p.add_argument(
        "--platform-filter",
        metavar="PLATFORM",
        dest="platform_filter",
        help="Filter by platform when used with --check-session",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.dry_run:
        DRY_RUN = True
        os.environ["DRY_RUN"] = "true"

    # ── Login mode ────────────────────────────────────────────
    if args.login:
        do_login(args.login)
        sys.exit(0)

    # ── Session check ─────────────────────────────────────────
    if args.check_session:
        check_sessions(args.platform_filter)
        sys.exit(0)

    # ── Execute modes ─────────────────────────────────────────
    executor = SocialExecutorV2()

    if args.execute:
        # Resolve path: accept full path, relative, or just filename in Approved/
        target = Path(args.execute)
        if not target.is_absolute():
            # Try as-is first, then relative to vault, then inside Approved/
            if (VAULT_PATH / target).exists():
                target = VAULT_PATH / target
            elif (APPROVED_PATH / target.name).exists():
                target = APPROVED_PATH / target.name
            else:
                target = VAULT_PATH / target

        print_banner("execute", str(target.name))
        ok = executor.execute_file(target)
        sys.exit(0 if ok else 1)

    elif args.platform:
        if args.platform not in SUPPORTED_PLATFORMS:
            print(f"[ERROR] Unknown platform: {args.platform}")
            sys.exit(1)
        print_banner("platform", args.platform)
        executor.execute_all(platform=args.platform)

    elif args.all:
        print_banner("all platforms")
        executor.execute_all()
