"""
facebook_debug.py
-----------------
Debug script — screenshots + element dump at every step.

Run: python facebook_debug.py
Screenshots saved to: Logs/screenshots/
"""

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

VAULT   = Path(__file__).parent.parent
SS_DIR  = VAULT / "Logs" / "screenshots"
SESSION = Path(__file__).parent / "sessions" / "facebook"
SS_DIR.mkdir(parents=True, exist_ok=True)

POST = "Testing AI Employee Vault automation on Facebook. Building an autonomous AI employee system for Hackathon 2026. #AI #Automation #BuildInPublic"

def ss(page, name):
    path = SS_DIR / f"fb-{name}.png"
    page.screenshot(path=str(path))
    print(f"  [screenshot] {path.name}")

def run():
    print("\n=== Facebook Debug Poster ===\n")
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION),
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        # Step 1: Load Facebook
        print("Step 1: Opening facebook.com ...")
        try:
            page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")
        page.wait_for_timeout(4000)
        ss(page, "01-loaded")
        print(f"  URL: {page.url}")

        # Step 2: Check login
        if "login" in page.url or "checkpoint" in page.url:
            print("  NOT logged in — please log in manually.")
            print("  Waiting 90 seconds ...")
            try:
                page.wait_for_function(
                    "() => !window.location.href.includes('login') && !window.location.href.includes('checkpoint')",
                    timeout=90000,
                )
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

        # Step 3: Find "What's on your mind" composer
        print("Step 3: Finding post composer ...")
        composer_selectors = [
            '[aria-label="Create a post"]',
            '[aria-placeholder="What\'s on your mind"]',
            'div[role="button"]:has-text("What\'s on your mind")',
            'span:has-text("What\'s on your mind")',
            '[placeholder="What\'s on your mind"]',
            'div[data-pagelet="FeedUnit_0"] [role="button"]',
        ]
        triggered = False
        for sel in composer_selectors:
            try:
                elem = page.wait_for_selector(sel, timeout=5000)
                print(f"  Found: {sel}")
                elem.click()
                triggered = True
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not triggered:
            print("  Dumping all buttons on page ...")
            buttons = page.query_selector_all("[role='button'], button")
            for b in buttons[:30]:
                try:
                    txt  = b.inner_text().strip()[:60]
                    aria = b.get_attribute("aria-label") or ""
                    ph   = b.get_attribute("aria-placeholder") or ""
                    print(f"  text='{txt}' aria='{aria}' placeholder='{ph}'")
                except:
                    pass
            ss(page, "03-no-composer")
            browser.close()
            return

        page.wait_for_timeout(3000)
        ss(page, "03-after-composer-click")

        # Step 4: Find text editor inside dialog
        print("Step 4: Finding post editor ...")
        editor = None
        editor_selectors = [
            '[contenteditable="true"][role="textbox"]',
            '[data-lexical-editor="true"]',
            '[aria-label="What\'s on your mind"]',
            '[aria-label*="mind"]',
            'div[contenteditable="true"]',
            '[role="dialog"] [contenteditable="true"]',
            '[role="dialog"] [role="textbox"]',
        ]
        for sel in editor_selectors:
            try:
                editor = page.wait_for_selector(sel, timeout=10000)
                print(f"  Found editor: {sel}")
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        if not editor:
            ss(page, "04-no-editor")
            print("  FAILED: No editor. Dumping contenteditable elements...")
            elems = page.query_selector_all('[contenteditable], [role="textbox"], [role="dialog"] *')
            for e in elems[:20]:
                try:
                    tag  = e.evaluate('e=>e.tagName')
                    role = e.get_attribute("role") or ""
                    ce   = e.get_attribute("contenteditable") or ""
                    aria = e.get_attribute("aria-label") or ""
                    tid  = e.get_attribute("data-testid") or ""
                    print(f"  tag={tag} role='{role}' ce='{ce}' aria='{aria}' testid='{tid}'")
                except:
                    pass
            browser.close()
            return

        # Step 5: Type content
        print("Step 5: Typing post content ...")
        editor.click()
        page.wait_for_timeout(500)
        page.keyboard.type(POST, delay=30)
        page.wait_for_timeout(2000)
        ss(page, "05-typed")
        print(f"  Typed {len(POST)} chars.")

        # Step 6: Find Post button
        print("Step 6: Finding Post button ...")
        post_btn = None
        post_selectors = [
            'div[aria-label="Post"][role="button"]',
            'button[type="submit"]:has-text("Post")',
            'div[role="button"]:has-text("Post")',
            '[role="dialog"] div[role="button"]:has-text("Post")',
        ]
        for sel in post_selectors:
            try:
                btn = page.wait_for_selector(sel, timeout=5000)
                enabled = btn.is_enabled()
                print(f"  Found: {sel} | enabled={enabled}")
                if enabled:
                    post_btn = btn
                    break
            except PWTimeout:
                print(f"  Not found: {sel}")

        ss(page, "06-before-post")

        if not post_btn:
            print("  FAILED: No Post button found.")
            browser.close()
            return

        # Step 7: Post
        print("Step 7: Clicking Post ...")
        post_btn.click()
        page.wait_for_timeout(5000)
        ss(page, "07-after-post")
        print(f"\n✅ Done! Check screenshot fb-07 to confirm.")
        print(f"  Screenshots at: {SS_DIR}")

        browser.close()

if __name__ == "__main__":
    run()
