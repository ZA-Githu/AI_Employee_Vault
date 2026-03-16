"""
instagram_debug.py - Find the correct Create button selector on Instagram.
Run: python instagram_debug.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

VAULT   = Path(__file__).parent.parent
SS_DIR  = VAULT / "Logs" / "screenshots"
SESSION = Path(__file__).parent / "sessions" / "instagram"
IMAGE   = str(VAULT / "Logs" / "screenshots" / "06-content-typed.png")
SS_DIR.mkdir(parents=True, exist_ok=True)

CAPTION = "Testing AI Employee Vault automation on Instagram. Hackathon 2026. #AI #Automation #BuildInPublic"

def ss(page, name):
    path = SS_DIR / f"ig-{name}.png"
    page.screenshot(path=str(path))
    print(f"  [screenshot] {path.name}")

def run():
    print("\n=== Instagram Debug Poster ===\n")
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION),
            headless=False,
            viewport={"width": 1366, "height": 900},
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        print("Step 1: Opening instagram.com ...")
        page.goto("https://www.instagram.com", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        ss(page, "01-loaded")
        print(f"  URL: {page.url}")

        # Check actual page content — Instagram shows login form even at root URL
        try:
            page.wait_for_selector('a[href="/"][role="link"], [aria-label="Home"]', timeout=5000)
            print("  Already logged in.")
        except PWTimeout:
            print("  NOT logged in — please log in manually (90s) ...")
            try:
                page.wait_for_selector(
                    'a[href="/"][role="link"], [aria-label="Home"]',
                    timeout=90000,
                )
                page.wait_for_timeout(3000)
                print("  Logged in!")
            except PWTimeout:
                print("  LOGIN TIMED OUT"); browser.close(); return

        ss(page, "02-home")

        # Wait for page to fully settle after login
        page.wait_for_timeout(3000)
        ss(page, "02b-settled")

        # Dump all nav links and buttons to find Create button
        print("\nStep 2: Dumping all nav links and buttons ...")
        result = page.evaluate("""() => {
            const elems = [...document.querySelectorAll('a, button, [role=button], [role=link]')];
            return elems.slice(0, 50).map(e => ({
                tag: e.tagName,
                aria: e.getAttribute('aria-label') || '',
                href: e.getAttribute('href') || '',
                text: (e.innerText || '').trim().slice(0, 40),
                svgAria: (e.querySelector('svg') ? e.querySelector('svg').getAttribute('aria-label') : '') || ''
            }));
        }""")
        for e in result:
            if e['aria'] or e['href'] or e['svgAria']:
                print(f"  tag={e['tag']} aria='{e['aria']}' href='{e['href']}' svg='{e['svgAria']}' text='{e['text']}'")


        # Step 3: Click New post and wait for dialog
        print("\nStep 3: Clicking New post ...")
        page.click('[aria-label="New post"]', timeout=5000)
        page.wait_for_timeout(4000)
        ss(page, "03-dialog")

        # Dump ALL visible text to find the "Select from computer" button text
        print("  Dumping all buttons/text in dialog ...")
        all_btns = page.evaluate("""() => {
            return [...document.querySelectorAll('button, [role=button], [role=dialog] *')]
                .map(e => ({
                    tag: e.tagName,
                    text: (e.innerText || e.textContent || '').trim().slice(0, 60),
                    role: e.getAttribute('role') || '',
                    aria: e.getAttribute('aria-label') || ''
                }))
                .filter(e => e.text && e.text.length > 1)
                .slice(0, 30)
        }""")
        for b in all_btns:
            print(f"  tag={b['tag']} role='{b['role']}' aria='{b['aria']}' text='{b['text']}'")

        # Step 4: Intercept file chooser by clicking "Select from computer"
        print("\nStep 4: Intercepting file chooser ...")
        try:
            with page.expect_file_chooser(timeout=15000) as fc_info:
                # Try all possible button texts
                for btn_text in ["Select from computer", "Select From Computer", "Choose", "Upload", "Browse"]:
                    try:
                        page.click(f'text="{btn_text}"', timeout=3000)
                        print(f"  Clicked: {btn_text}")
                        break
                    except:
                        pass
            file_chooser = fc_info.value
            print(f"  File chooser intercepted! Setting: {IMAGE}")
            file_chooser.set_files(IMAGE)
            page.wait_for_timeout(3000)
            ss(page, "04-after-upload")
        except Exception as e:
            print(f"  File chooser failed: {e}")
            ss(page, "04-failed")
            browser.close()
            return


        # Step 5: Click Next buttons
        print("\nStep 5: Clicking Next ...")
        for i in range(3):
            try:
                page.click('button:has-text("Next"), div[role="button"]:has-text("Next")', timeout=5000)
                print(f"  Clicked Next ({i+1})")
                page.wait_for_timeout(2000)
            except PWTimeout:
                print(f"  No Next button at step {i+1}")
                break
        ss(page, "05-after-next")

        # Step 6: Type caption
        print("\nStep 6: Typing caption ...")
        cap_selectors = [
            'textarea[aria-label*="caption"]',
            'div[aria-label*="caption"]',
            'textarea[placeholder*="caption"]',
            'div[contenteditable="true"]',
        ]
        typed = False
        for sel in cap_selectors:
            try:
                cap = page.wait_for_selector(sel, timeout=5000)
                print(f"  Caption field: {sel}")
                cap.click()
                page.wait_for_timeout(500)
                page.keyboard.type(CAPTION, delay=20)
                typed = True
                break
            except PWTimeout:
                print(f"  Not found: {sel}")

        page.wait_for_timeout(1000)
        ss(page, "06-caption")

        # Step 7: Share
        print("\nStep 7: Clicking Share ...")
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
                    print(f"  Shared via: {sel}")
                    break
            except PWTimeout:
                print(f"  Not found: {sel}")

        page.wait_for_timeout(5000)
        ss(page, "07-after-share")
        if shared:
            print("\n✅ Done! Check your Instagram.")
        else:
            print("\n  FAILED: No Share button found.")
        print(f"  Screenshots: {SS_DIR}")
        browser.close()

if __name__ == "__main__":
    run()
