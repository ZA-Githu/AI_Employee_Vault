"""Quick Twitter post test — same pattern as LinkedIn/Facebook."""
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SESSION = Path(__file__).parent / "sessions" / "twitter"
TWEET   = "Testing AI Employee Vault automation. Hackathon 2026 — autonomous AI employee system. #AI #Automation #BuildInPublic"

with sync_playwright() as pw:
    browser = pw.chromium.launch_persistent_context(
        user_data_dir=str(SESSION), headless=False,
        viewport={"width": 1366, "height": 900},
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    )
    page = browser.pages[0] if browser.pages else browser.new_page()
    page.goto("https://x.com/home", wait_until="commit", timeout=60000)
    page.wait_for_timeout(5000)

    if "login" in page.url or "flow" in page.url:
        print("Please log in manually...")
        page.wait_for_url("**/home**", timeout=90000)
        page.wait_for_timeout(3000)

    print("Logged in. Clicking compose...")
    page.click('[data-testid="SideNav_NewTweet_Button"]', timeout=10000)
    page.wait_for_timeout(5000)

    print("Finding editor...")
    for sel in ['[data-testid="tweetTextarea_0"]', 'div[role="textbox"]', 'div[contenteditable="true"]']:
        try:
            e = page.wait_for_selector(sel, timeout=15000)
            e.click()
            page.wait_for_timeout(500)
            page.keyboard.type(TWEET, delay=30)
            print(f"Typed via: {sel}")
            break
        except PWTimeout:
            continue

    page.wait_for_timeout(3000)

    print("Clicking Post...")
    posted = False
    for sel in ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']:
        try:
            btn = page.wait_for_selector(sel, timeout=8000)
            print(f"  Found button: {sel} | enabled={btn.is_enabled()}")
            # Wait up to 10s for button to enable
            for _ in range(20):
                if btn.is_enabled(): break
                page.wait_for_timeout(500)
            print(f"  After wait, enabled={btn.is_enabled()}")
            if btn.is_enabled():
                # Try JS click to bypass any overlay
                page.evaluate("el => el.click()", btn)
                print("✅ Tweet posted!")
                posted = True
                break
        except PWTimeout:
            print(f"  Not found: {sel}")
    if not posted:
        print("FAILED: Post button not clickable. Dumping buttons...")
        btns = page.evaluate("""() => [...document.querySelectorAll('[data-testid]')]
            .map(e => ({tid: e.getAttribute('data-testid'), text: (e.innerText||'').trim().slice(0,30), enabled: !e.disabled}))
            .filter(e => e.tid)""")
        for b in btns:
            print(f"  testid={b['tid']} text='{b['text']}' enabled={b['enabled']}")

    page.wait_for_timeout(5000)
    browser.close()
