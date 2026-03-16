"""Quick Instagram post test — uses file chooser interceptor."""
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION = Path(__file__).parent / "sessions" / "instagram"
IMAGE   = str(Path(__file__).parent.parent / "Logs" / "screenshots" / "06-content-typed.png")
CAPTION = "Testing AI Employee Vault automation. Hackathon 2026 — autonomous AI employee system. #AI #Automation #BuildInPublic"

with sync_playwright() as pw:
    browser = pw.chromium.launch_persistent_context(
        user_data_dir=str(SESSION), headless=False,
        viewport={"width": 1366, "height": 900},
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto("https://www.instagram.com", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Login check by page content
    try:
        page.wait_for_selector('a[href="#"][role="link"], svg[aria-label="New post"]', timeout=6000)
        print("Logged in.")
    except PWTimeout:
        print("Please log in manually (90s)...")
        page.wait_for_selector('svg[aria-label="New post"]', timeout=90000)
        page.wait_for_timeout(2000)
        print("Logged in!")

    # Step 1: Click New post using Playwright native click on SVG
    print("Clicking New post...")
    page.click('svg[aria-label="New post"]', timeout=5000)

    # Step 2: Wait for dialog to appear
    print("Waiting for dialog...")
    try:
        page.wait_for_selector('[role="dialog"]', timeout=10000)
        print("  Dialog appeared!")
    except PWTimeout:
        print("  No dialog — waiting 5s anyway...")
        page.wait_for_timeout(5000)

    # Step 3: Dump dialog buttons
    btns = page.evaluate("""() => {
        const dialog = document.querySelector('[role="dialog"]');
        const root = dialog || document;
        return [...root.querySelectorAll('button, [role=button]')]
            .map(e => (e.innerText || e.textContent || '').trim())
            .filter(t => t.length > 0);
    }""")
    print(f"  Dialog buttons: {btns}")

    # Step 4: Intercept file chooser
    print("Intercepting file chooser...")
    try:
        with page.expect_file_chooser(timeout=15000) as fc:
            for txt in ["Select from computer", "Select From Computer"]:
                try:
                    page.get_by_role("button", name=txt).click(timeout=3000)
                    print(f"  Clicked: {txt}")
                    break
                except:
                    try:
                        page.locator(f'[role="dialog"] button:has-text("{txt}")').click(timeout=3000)
                        break
                    except: pass
        fc.value.set_files(IMAGE)
        print("✅ File uploaded!")
    except Exception as e:
        print(f"File chooser failed: {e}")
        browser.close()
        exit()

    page.wait_for_timeout(3000)

    # Click Next (up to 2 times for crop/filter steps)
    for i in range(2):
        try:
            page.click('button:has-text("Next"), div[role="button"]:has-text("Next")', timeout=5000)
            print(f"Clicked Next ({i+1})")
            page.wait_for_timeout(2000)
        except PWTimeout:
            break

    # Type caption
    print("Typing caption...")
    for sel in ['textarea[aria-label*="caption"], div[aria-label*="caption"]', 'div[contenteditable="true"]', 'textarea']:
        try:
            cap = page.wait_for_selector(sel, timeout=5000)
            cap.click()
            page.wait_for_timeout(500)
            page.keyboard.type(CAPTION, delay=20)
            print(f"Caption typed via: {sel}")
            break
        except PWTimeout:
            continue

    page.wait_for_timeout(1000)

    # Click Share
    print("Clicking Share...")
    for sel in ['div[role="button"]:has-text("Share")', 'button:has-text("Share")']:
        try:
            btn = page.wait_for_selector(sel, timeout=5000)
            if btn.is_enabled():
                page.evaluate("el => el.click()", btn)
                print("✅ Instagram post shared!")
                break
        except PWTimeout:
            continue

    page.wait_for_timeout(5000)
    browser.close()
