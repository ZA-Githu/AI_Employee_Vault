"""
twitter_debug.py
----------------
Debug script — takes a screenshot at every step to see exactly
what X.com is showing and why the compose dialog won't open.

Run: python twitter_debug.py
Screenshots saved to: Logs/screenshots/
"""

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

VAULT    = Path(__file__).parent.parent
SS_DIR   = VAULT / "Logs" / "screenshots"
SESSION  = Path(__file__).parent / "sessions" / "twitter"
SS_DIR.mkdir(parents=True, exist_ok=True)

TWEET = "Testing AI Employee Vault automation on X. Building an autonomous AI employee system for Hackathon 2026. #AI #Automation #BuildInPublic"

def ss(page, name):
    path = SS_DIR / f"tw-{name}.png"
    page.screenshot(path=str(path))
    print(f"  [screenshot] {path.name}")

def run():
    print("\n=== Twitter/X Debug Poster ===\n")
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION),
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        # Step 1: Load X home
        print("Step 1: Opening x.com/home ...")
        try:
            page.goto("https://x.com/home", wait_until="commit", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")
        page.wait_for_timeout(4000)
        ss(page, "01-loaded")
        print(f"  URL: {page.url}")

        # Step 2: Check login
        if "login" in page.url or "i/flow" in page.url:
            print("  NOT logged in — please log in manually.")
            print("  Waiting 90 seconds ...")
            try:
                page.wait_for_url("**/home**", timeout=90000)
                page.wait_for_timeout(3000)
                ss(page, "02-after-login")
                print("  Logged in!")
            except PWTimeout:
                print("  LOGIN TIMED OUT")
                browser.close()
                return
        else:
            print("  Already logged in.")
            ss(page, "02-logged-in")

        # Step 3: Find and click compose / "Post" button
        print("Step 3: Finding compose button ...")
        compose_selectors = [
            '[data-testid="SideNav_NewTweet_Button"]',
            'a[href="/compose/post"]',
            'a[href="/compose/tweet"]',
            'div[aria-label="Post"][role="button"]',
            'button[aria-label="Post"]',
            '[data-testid="tweetButtonInline"]',
        ]
        triggered = False
        for sel in compose_selectors:
            try:
                elem = page.wait_for_selector(sel, timeout=4000)
                print(f"  Found: {sel}")
                elem.click()
                triggered = True
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not triggered:
            print("  Trying inline compose box on feed ...")
            try:
                elem = page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=5000)
                print("  Found inline textarea!")
                elem.click()
                triggered = True
            except PWTimeout:
                print("  Not found: tweetTextarea_0")

        # Wait longer for compose modal to fully load
        page.wait_for_timeout(4000)
        ss(page, "03-after-compose-click")

        if not triggered:
            print("\n  FAILED: Cannot open compose. Dumping all buttons/links on page...")
            # Print all buttons
            buttons = page.query_selector_all("button, [role='button'], a[href]")
            for b in buttons[:30]:
                try:
                    txt = b.inner_text().strip()[:60]
                    aria = b.get_attribute("aria-label") or ""
                    tid = b.get_attribute("data-testid") or ""
                    href = b.get_attribute("href") or ""
                    print(f"  tag={b.evaluate('e=>e.tagName')} text='{txt}' aria='{aria}' testid='{tid}' href='{href}'")
                except:
                    pass
            browser.close()
            return

        # Step 4: Find text editor
        print("Step 4: Waiting for compose dialog to load ...")
        # Wait for the dialog/modal to appear
        try:
            page.wait_for_selector('[role="dialog"]', timeout=8000)
            print("  Dialog appeared.")
        except PWTimeout:
            print("  No dialog found — checking page directly.")
        page.wait_for_timeout(2000)
        ss(page, "04-dialog-check")
        print("Step 4: Finding tweet editor (waiting up to 15s) ...")
        editor = None
        editor_selectors = [
            '[data-testid="tweetTextarea_0"]',
            '[data-testid="tweetTextarea_0RichTextInputContainer"]',
            'div[role="textbox"]',
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
            '[role="dialog"] [contenteditable]',
            '[role="dialog"] [role="textbox"]',
        ]
        for sel in editor_selectors:
            try:
                editor = page.wait_for_selector(sel, timeout=15000)
                print(f"  Found editor: {sel}")
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not editor:
            ss(page, "04-no-editor")
            print("  FAILED: No editor found. Dumping all editable elements...")
            elems = page.query_selector_all('[contenteditable], [role="textbox"], [role="dialog"] *, textarea, input')
            for e in elems:
                try:
                    tag  = e.evaluate('e=>e.tagName')
                    role = e.get_attribute("role") or ""
                    tid  = e.get_attribute("data-testid") or ""
                    ce   = e.get_attribute("contenteditable") or ""
                    aria = e.get_attribute("aria-label") or ""
                    cls  = e.get_attribute("class") or ""
                    print(f"  tag={tag} role='{role}' testid='{tid}' contenteditable='{ce}' aria='{aria}' class='{cls[:60]}'")
                except:
                    pass
            browser.close()
            return

        # Step 5: Type tweet
        print("Step 5: Typing tweet ...")
        editor.click()
        page.wait_for_timeout(500)
        page.keyboard.type(TWEET, delay=30)
        page.wait_for_timeout(2000)
        ss(page, "05-typed")
        print(f"  Typed {len(TWEET)} chars.")

        # Step 6: Find Post button
        print("Step 6: Finding Post button ...")
        post_btn = None
        post_selectors = [
            '[data-testid="tweetButton"]',
            '[data-testid="tweetButtonInline"]',
            'button[data-testid="tweetButton"]',
            'div[data-testid="tweetButton"]',
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
                    page.wait_for_timeout(2000)
                    if btn.is_enabled():
                        post_btn = btn
                        break
            except PWTimeout:
                print(f"  Not found: {sel}")

        ss(page, "06-before-post")

        if not post_btn:
            print("\n  FAILED: No enabled Post button. Check screenshot tw-06.")
            browser.close()
            return

        # Step 7: Post
        print("Step 7: Clicking Post ...")
        post_btn.click()
        page.wait_for_timeout(5000)
        ss(page, "07-after-post")
        print(f"\n✅ Done! Check screenshot tw-07 to confirm post.")
        print(f"  Screenshots at: {SS_DIR}")

        browser.close()

if __name__ == "__main__":
    run()
