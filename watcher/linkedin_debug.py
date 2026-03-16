"""
linkedin_debug.py
-----------------
Debug script — takes a screenshot at every step so we can see exactly
what LinkedIn is showing and why the post is not going through.

Run: python linkedin_debug.py
Screenshots saved to: Logs/screenshots/
"""

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

VAULT     = Path(__file__).parent.parent
SS_DIR    = VAULT / "Logs" / "screenshots"
SESSION   = Path(__file__).parent / "sessions" / "linkedin"
SS_DIR.mkdir(parents=True, exist_ok=True)

POST_TEXT = "Testing AI Employee Vault post automation. Building an autonomous AI employee system for Hackathon 2026. #AI #Automation #BuildInPublic"

def ss(page, name):
    path = SS_DIR / f"{name}.png"
    page.screenshot(path=str(path))
    print(f"  [screenshot] {path.name}")

def run():
    print("\n=== LinkedIn Debug Poster ===\n")
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION),
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        # Step 1: Go to LinkedIn feed
        print("Step 1: Opening LinkedIn feed...")
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        ss(page, "01-feed-loaded")

        # Step 2: Check login
        print("Step 2: Checking login status...")
        if "login" in page.url or "signup" in page.url:
            print("  NOT logged in — please log in manually in the browser.")
            print("  Waiting 60 seconds for manual login...")
            try:
                page.wait_for_url("**/feed/**", timeout=60000)
                page.wait_for_timeout(2000)
                ss(page, "02-after-login")
                print("  Logged in!")
            except PWTimeout:
                print("  LOGIN TIMED OUT")
                browser.close()
                return
        else:
            print("  Already logged in.")
            ss(page, "02-logged-in")

        # Step 3: Find and click "Start a post"
        print("Step 3: Finding 'Start a post' button...")
        triggered = False
        share_selectors = [
            '.share-box-feed-entry__trigger',
            'button:has-text("Start a post")',
            '[data-control-name="share.sharebox_text"]',
            '.share-creation-state__placeholder',
            'button[aria-label="Start a post"]',
            '[data-view-name="share-entry-point"]',
            '.artdeco-card .share-box-feed-entry__top-bar',
        ]
        for sel in share_selectors:
            try:
                elem = page.wait_for_selector(sel, timeout=4000)
                print(f"  Found: {sel}")
                elem.click()
                triggered = True
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not triggered:
            print("  FAILED: Could not find 'Start a post' button")
            print("  Trying JavaScript click on any share trigger...")
            try:
                page.evaluate("""
                    const btns = [...document.querySelectorAll('button')];
                    const btn = btns.find(b => b.textContent.includes('Start a post'));
                    if(btn) { btn.click(); console.log('clicked'); }
                """)
                triggered = True
            except Exception as e:
                print(f"  JS click also failed: {e}")

        page.wait_for_timeout(2500)
        ss(page, "03-after-share-click")

        if not triggered:
            print("\nDEBUG: Cannot open post composer. Check screenshot 03.")
            browser.close()
            return

        # Step 4: Find editor
        print("Step 4: Finding post editor...")
        editor = None
        editor_selectors = [
            '.ql-editor[contenteditable="true"]',
            '[data-testid="ql-editor"]',
            '[aria-label="Text editor for creating content"]',
            '.editor-content [contenteditable="true"]',
            'div[contenteditable="true"]',
        ]
        for sel in editor_selectors:
            try:
                editor = page.wait_for_selector(sel, timeout=5000)
                print(f"  Found editor: {sel}")
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not editor:
            print("  FAILED: Could not find post editor")
            ss(page, "04-no-editor")
            browser.close()
            return

        # Step 5: Type content
        print("Step 5: Clicking editor and typing content...")
        editor.click()
        page.wait_for_timeout(500)
        ss(page, "05-editor-focused")

        page.keyboard.type(POST_TEXT, delay=30)
        page.wait_for_timeout(2000)
        ss(page, "06-content-typed")
        print(f"  Typed {len(POST_TEXT)} characters.")

        # Step 6: Find Post button
        print("Step 6: Finding Post button...")
        post_btn = None
        post_selectors = [
            'button.share-actions__primary-action',
            'button[data-control-name="share.post"]',
            '.share-box_actions button.artdeco-button--primary',
            'button:has-text("Post")',
            '[aria-label="Post"]',
        ]
        for sel in post_selectors:
            try:
                btn = page.wait_for_selector(sel, timeout=5000)
                enabled = btn.is_enabled()
                print(f"  Found: {sel} | enabled={enabled}")
                if enabled:
                    post_btn = btn
                    break
                else:
                    print(f"  Button exists but disabled. Waiting 3s...")
                    page.wait_for_timeout(3000)
                    enabled = btn.is_enabled()
                    print(f"  After wait, enabled={enabled}")
                    if enabled:
                        post_btn = btn
                        break
            except PWTimeout:
                print(f"  Not found: {sel}")

        ss(page, "07-before-post-click")

        if not post_btn:
            print("  FAILED: No enabled Post button found. Check screenshots.")
            browser.close()
            return

        # Step 7: Click Post
        print("Step 7: Clicking Post button...")
        post_btn.click()
        page.wait_for_timeout(5000)
        ss(page, "08-after-post")
        print("\n✅ Post button clicked! Check screenshot 08 to confirm post was published.")
        print(f"  Screenshots saved to: {SS_DIR}")

        browser.close()

if __name__ == "__main__":
    run()
