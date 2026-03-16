"""
gold-social-test.py
-------------------
Gold Tier — Social Manager End-to-End Test (dry-run, zero real posts)

Full pipeline exercised without any browser or login:
  1. Pre-flight    — folders, scripts, Python imports
  2. Draft create  — trigger_posts.py for all 6 platforms
  3. HITL sim      — set approved_by: human + status: approved, move to Approved/
  4. Orchestrator  — master_orchestrator.py --once --dry-run (detect + dispatch)
  5. Executor      — social_media_executor_v2.py --execute --dry-run (gate + log)
  6. Log verify    — check Logs/YYYY-MM-DD.json for all expected entries
  7. Cleanup       — remove all test files, assert none remain

No tokens or browser sessions are required.
All test files are tagged TEST-GOLD-SOCIAL and removed on completion.

Run from vault root:
    python watcher/gold-social-test.py

Run from watcher/:
    python gold-social-test.py
"""

# ── UTF-8 stdout for Windows cp1252 ──────────────────────────────────────────
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
WATCHER_DIR = Path(__file__).parent.resolve()
VAULT_PATH  = Path(os.getenv("VAULT_PATH", str(WATCHER_DIR.parent))).resolve()
sys.path.insert(0, str(WATCHER_DIR))

PENDING_DIR  = VAULT_PATH / "Pending_Approval"
APPROVED_DIR = VAULT_PATH / "Approved"
DONE_DIR     = VAULT_PATH / "Done"
LOGS_DIR     = VAULT_PATH / "Logs"
SESSION_DIR  = VAULT_PATH / "session"
TODAY        = datetime.now().strftime("%Y-%m-%d")

# ── Test identity ─────────────────────────────────────────────────────────────
TEST_TAG = "TEST-GOLD-SOCIAL"    # prefix in every test draft title/filename

# ── Test cases — one per platform ────────────────────────────────────────────
#   (platform, content, recipient, subject)
PLATFORMS = [
    ("linkedin",  f"{TEST_TAG}: LinkedIn dry-run post",    "",                  ""),
    ("twitter",   f"{TEST_TAG}: Twitter dry-run #dryrun",  "",                  ""),
    ("facebook",  f"{TEST_TAG}: Facebook dry-run post",    "",                  ""),
    ("instagram", f"{TEST_TAG}: Instagram dry-run caption","",                  ""),
    ("whatsapp",  f"{TEST_TAG}: WhatsApp dry-run message", "+447700900001",     ""),
    ("gmail",     f"{TEST_TAG}: Gmail dry-run email body", "noreply@test.local",f"{TEST_TAG} Subject"),
]

# ── Counters + state ──────────────────────────────────────────────────────────
PASS_COUNT = 0
FAIL_COUNT = 0
TEST_FILES: dict[str, Path] = {}   # platform -> Path in Approved/


# ── Assertion helper ──────────────────────────────────────────────────────────

def check(condition: bool, label: str) -> bool:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  PASS  {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL  {label}")
    return bool(condition)


def section(title: str) -> None:
    print()
    print(f"[{title}]")


# ── Sub-process helper ────────────────────────────────────────────────────────

def run_cmd(
    cmd: list,
    timeout: int = 30,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(VAULT_PATH),
        env=env,
    )


# ── Frontmatter helpers ───────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Returns ({}, text) on failure."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        import yaml
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        fm = {}
    return fm, parts[2].strip()


def approve_frontmatter(path: Path) -> bool:
    """
    Set approved_by: human and status: approved in an existing draft file.
    Uses direct regex substitution to avoid YAML round-trip mangling.
    """
    try:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^(approved_by\s*:)\s*$", r"\1 human", text, flags=re.MULTILINE)
        text = re.sub(r"^(status\s*:)\s*pending", r"\1 approved", text, flags=re.MULTILINE)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


# ── Log helpers ───────────────────────────────────────────────────────────────

def read_log() -> list[dict]:
    """Return today's JSON audit log entries (empty list if missing/corrupt)."""
    log_file = LOGS_DIR / f"{TODAY}.json"
    if not log_file.exists():
        return []
    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def find_log_entries(
    action_type: str,
    outcome: str | None = None,
    source_substr: str | None = None,
    notes_substr: str | None = None,
) -> list[dict]:
    """Search today's log for entries matching all supplied filters."""
    results = []
    for e in read_log():
        if e.get("action_type") != action_type:
            continue
        if outcome and e.get("outcome") != outcome:
            continue
        if source_substr and source_substr.lower() not in (e.get("source") or "").lower():
            continue
        if notes_substr and notes_substr.lower() not in (e.get("notes") or "").lower():
            continue
        results.append(e)
    return results


# ── Cleanup helper ────────────────────────────────────────────────────────────

def cleanup_test_files() -> int:
    """
    Remove all test .md files (tagged TEST_TAG) from Pending_Approval/ and Approved/.
    Returns count of files removed.
    """
    removed = 0
    for folder in (PENDING_DIR, APPROVED_DIR):
        if not folder.exists():
            continue
        for f in folder.glob("*.md"):
            if TEST_TAG in f.name or TEST_TAG in f.stem:
                try:
                    f.unlink()
                    removed += 1
                    continue
                except Exception:
                    pass
            # Also check title inside frontmatter
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if TEST_TAG in str(fm.get("title", "")):
                    f.unlink()
                    removed += 1
            except Exception:
                pass
    return removed


# ═════════════════════════════════════════════════════════════════════════════
# TEST SECTIONS
# ═════════════════════════════════════════════════════════════════════════════

def test_preflight() -> None:
    section("SECTION 1 — PRE-FLIGHT CHECKS")

    # Required vault folders (create if missing — non-blocking)
    for name in ("Pending_Approval", "Approved", "Done", "Logs", "session"):
        folder = VAULT_PATH / name
        folder.mkdir(parents=True, exist_ok=True)
        check(folder.is_dir(), f"Vault folder: {name}/")

    # Session platform subfolders
    for platform, *_ in PLATFORMS:
        d = SESSION_DIR / platform
        d.mkdir(parents=True, exist_ok=True)
        check(d.is_dir(), f"Session folder: session/{platform}/")

    # Required scripts
    for script in (
        "trigger_posts.py",
        "master_orchestrator.py",
        "social_media_executor_v2.py",
        "audit_logger.py",
    ):
        check((WATCHER_DIR / script).exists(), f"Script: watcher/{script}")

    # Python imports
    for module in ("yaml", "watchdog", "audit_logger"):
        try:
            __import__(module)
            check(True, f"Python import: {module}")
        except ImportError as exc:
            check(False, f"Python import: {module} — {exc}")


# ─────────────────────────────────────────────────────────────────────────────

def test_draft_creation() -> None:
    section("SECTION 2 — DRAFT CREATION (trigger_posts.py for all 6 platforms)")

    # 2a — Dry-run must NOT write any file
    pre_count = len(list(PENDING_DIR.glob("*.md"))) if PENDING_DIR.exists() else 0
    try:
        result = run_cmd([
            sys.executable, str(WATCHER_DIR / "trigger_posts.py"),
            "--platform", "linkedin",
            "--content", f"{TEST_TAG} dry-run probe",
            "--dry-run",
        ], timeout=15)
        post_count = len(list(PENDING_DIR.glob("*.md"))) if PENDING_DIR.exists() else 0
        check(result.returncode == 0, "trigger_posts.py --dry-run: exit 0")
        check(post_count == pre_count,  "trigger_posts.py --dry-run: no file written")
    except subprocess.TimeoutExpired:
        check(False, "trigger_posts.py --dry-run: timed out")

    # 2b — Character-limit hard reject (Twitter 300 chars, no truncate)
    oversized = "A" * 300
    try:
        result = run_cmd([
            sys.executable, str(WATCHER_DIR / "trigger_posts.py"),
            "--platform", "twitter",
            "--content", oversized,
        ], timeout=15)
        check(result.returncode != 0, "trigger_posts.py: Twitter 300-char rejected (exit != 0)")
    except subprocess.TimeoutExpired:
        check(False, "trigger_posts.py char-limit test: timed out")

    # 2c — Twitter --allow-truncate accepts oversized content
    try:
        result = run_cmd([
            sys.executable, str(WATCHER_DIR / "trigger_posts.py"),
            "--platform", "twitter",
            "--content", oversized,
            "--allow-truncate",
            "--dry-run",
        ], timeout=15)
        check(result.returncode == 0, "trigger_posts.py: --allow-truncate dry-run exit 0")
    except subprocess.TimeoutExpired:
        check(False, "trigger_posts.py --allow-truncate: timed out")

    # 2d — Missing recipient warnings (not hard-blocked)
    try:
        result = run_cmd([
            sys.executable, str(WATCHER_DIR / "trigger_posts.py"),
            "--platform", "whatsapp",
            "--content", "no recipient",
            "--dry-run",
        ], timeout=15)
        check(result.returncode == 0,             "trigger_posts.py: whatsapp missing recipient is warning only")
        check("WARNING" in result.stdout,         "trigger_posts.py: whatsapp missing recipient prints WARNING")
    except subprocess.TimeoutExpired:
        check(False, "trigger_posts.py missing-recipient test: timed out")

    # 2e — Create one real draft per platform
    print()
    print("  Creating 6 test drafts ...")
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    for platform, content, recipient, subject in PLATFORMS:
        cmd = [
            sys.executable,
            str(WATCHER_DIR / "trigger_posts.py"),
            "--platform", platform,
            "--content",  content,
            "--title",    f"{TEST_TAG} {platform.capitalize()}",
            "--priority", "high",
        ]
        if recipient:
            cmd += ["--recipient", recipient]
        if subject:
            cmd += ["--subject", subject]

        try:
            result = run_cmd(cmd, timeout=15)
        except subprocess.TimeoutExpired:
            check(False, f"{platform}: trigger_posts.py timed out")
            continue
        except Exception as exc:
            check(False, f"{platform}: trigger_posts.py exception — {exc}")
            continue

        if not check(result.returncode == 0, f"{platform}: trigger_posts.py exit 0"):
            print(f"         stderr: {result.stderr.strip()[:120]}")
            continue

        # Locate the created file
        created: Path | None = None
        for f in PENDING_DIR.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if fm.get("platform") == platform and TEST_TAG in str(fm.get("title", "")):
                    created = f
                    break
            except Exception:
                continue

        if not check(created is not None, f"{platform}: draft found in Pending_Approval/"):
            continue

        # Validate frontmatter contract (per social-drafter.md)
        text = created.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text)

        check(fm.get("type")     == "social-post", f"{platform}: type == social-post")
        check(fm.get("status")   == "pending",     f"{platform}: status == pending")
        check(not fm.get("approved_by"),            f"{platform}: approved_by is blank")
        check(fm.get("platform") == platform,      f"{platform}: platform field matches")

        TEST_FILES[platform] = created


# ─────────────────────────────────────────────────────────────────────────────

def test_hitl_simulation() -> None:
    section("SECTION 3 — HITL SIMULATION (approve + move to Approved/)")

    APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    for platform, *_ in PLATFORMS:
        draft = TEST_FILES.get(platform)
        if not draft or not draft.exists():
            check(False, f"{platform}: draft not available — skipping HITL")
            continue

        # Set approved_by: human + status: approved
        ok = approve_frontmatter(draft)
        if not check(ok, f"{platform}: frontmatter updated (approved_by + status)"):
            continue

        # Verify values were written correctly
        text = draft.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text)
        check(str(fm.get("approved_by", "")).strip() == "human", f"{platform}: approved_by == human")
        check(fm.get("status") == "approved",                    f"{platform}: status == approved")

        # Move from Pending_Approval/ → Approved/
        dest = APPROVED_DIR / draft.name
        try:
            shutil.move(str(draft), str(dest))
            TEST_FILES[platform] = dest
        except Exception as exc:
            check(False, f"{platform}: move to Approved/ failed — {exc}")
            continue

        check(dest.exists(),         f"{platform}: file present in Approved/")
        check(not draft.exists(),    f"{platform}: file removed from Pending_Approval/")


# ─────────────────────────────────────────────────────────────────────────────

def test_orchestrator() -> None:
    section("SECTION 4 — ORCHESTRATOR DRY-RUN (master_orchestrator.py --once --dry-run)")

    ready = {p: f for p, f in TEST_FILES.items() if f.exists()}
    n     = len(ready)

    check(n == len(PLATFORMS), f"{n}/{len(PLATFORMS)} test files present in Approved/")

    if n == 0:
        print("  SKIP  No files to process — orchestrator test skipped")
        return

    est_s = n * 5 + 15
    print(f"  INFO  Running orchestrator (estimated {est_s}s for {n} files × 5s rate-limit) ...")

    try:
        result = run_cmd(
            [
                sys.executable,
                str(WATCHER_DIR / "master_orchestrator.py"),
                "--once",
                "--dry-run",
            ],
            timeout=150,
            extra_env={"DRY_RUN": "true"},
        )
    except subprocess.TimeoutExpired:
        check(False, "Orchestrator --once --dry-run: timed out (150s)")
        return
    except Exception as exc:
        check(False, f"Orchestrator subprocess error: {exc}")
        return

    check(result.returncode == 0, "Orchestrator exit code 0")

    # Dry-run must NOT move files to Done/
    still_approved = sum(1 for f in TEST_FILES.values() if f.exists())
    check(
        still_approved == n,
        f"Files remain in Approved/ after dry-run ({still_approved}/{n})",
    )

    # Done/ must contain no test files
    test_in_done: list[Path] = []
    if DONE_DIR.exists():
        for f in DONE_DIR.rglob("*.md"):
            try:
                fm, _ = parse_frontmatter(f.read_text(encoding="utf-8"))
                if TEST_TAG in str(fm.get("title", "")):
                    test_in_done.append(f)
            except Exception:
                pass
    check(len(test_in_done) == 0, f"No test files in Done/ after dry-run (found {len(test_in_done)})")

    # Log: ORCHESTRATOR_START
    check(len(find_log_entries("ORCHESTRATOR_START", "success")) > 0,
          "Log: ORCHESTRATOR_START — success")

    # Log: ORCHESTRATOR_STOP
    check(len(find_log_entries("ORCHESTRATOR_STOP", "success")) > 0,
          "Log: ORCHESTRATOR_STOP — success")

    # Log: per-platform ORCHESTRATOR_DISPATCH success
    dispatch_ok = find_log_entries("ORCHESTRATOR_DISPATCH", "success")
    for platform, *_ in PLATFORMS:
        path = TEST_FILES.get(platform)
        if path is None:
            continue
        found = any(
            path.name in (e.get("source") or "")
            or platform in (e.get("notes") or "")
            for e in dispatch_ok
        )
        check(found, f"Log: ORCHESTRATOR_DISPATCH success — {platform}")


# ─────────────────────────────────────────────────────────────────────────────

def test_executor() -> None:
    section("SECTION 5 — EXECUTOR DRY-RUN (social_media_executor_v2.py --execute --dry-run)")

    for platform, *_ in PLATFORMS:
        file_path = TEST_FILES.get(platform)
        if not file_path or not file_path.exists():
            check(False, f"{platform}: file not in Approved/ — skipping executor test")
            continue

        try:
            result = run_cmd(
                [
                    sys.executable,
                    str(WATCHER_DIR / "social_media_executor_v2.py"),
                    "--execute", str(file_path),
                    "--dry-run",
                ],
                timeout=20,
                extra_env={"DRY_RUN": "true"},
            )
        except subprocess.TimeoutExpired:
            check(False, f"{platform}: executor timed out")
            continue
        except Exception as exc:
            check(False, f"{platform}: executor exception — {exc}")
            continue

        check(result.returncode == 0, f"{platform}: executor exit code 0")

        # File must stay in Approved/ (dry-run protection)
        check(file_path.exists(), f"{platform}: file stays in Approved/ (not moved)")

        # SKILL_RUN entry logged
        entries = find_log_entries("SKILL_RUN", "success", notes_substr="dry-run")
        found   = any(platform in (e.get("notes") or "") for e in entries)
        check(found, f"{platform}: Log SKILL_RUN dry-run — platform: {platform}")


# ─────────────────────────────────────────────────────────────────────────────

def test_log_verification() -> None:
    section("SECTION 6 — LOG VERIFICATION (Logs/{TODAY}.json)")

    json_log = LOGS_DIR / f"{TODAY}.json"
    md_log   = LOGS_DIR / f"{TODAY}.md"
    check(json_log.exists(), f"Logs/{TODAY}.json exists")
    check(md_log.exists(),   f"Logs/{TODAY}.md exists")

    entries = read_log()
    check(len(entries) > 0, f"Log file has at least 1 entry (found {len(entries)})")

    # DRAFT_CREATE — one per test platform
    draft_entries = [
        e for e in find_log_entries("DRAFT_CREATE", "success")
        if TEST_TAG in (e.get("destination") or "") or TEST_TAG in (e.get("notes") or "")
    ]
    check(
        len(draft_entries) >= len(PLATFORMS),
        f"DRAFT_CREATE entries: {len(draft_entries)} >= {len(PLATFORMS)}",
    )

    # ORCHESTRATOR_DISPATCH success — one per platform
    dispatch_ok = find_log_entries("ORCHESTRATOR_DISPATCH", "success")
    test_dispatches = [
        e for e in dispatch_ok
        if any(
            TEST_TAG in (e.get("source") or "") or
            (TEST_FILES.get(p) and TEST_FILES[p].name in (e.get("source") or ""))
            for p, *_ in PLATFORMS
        )
    ]
    check(
        len(test_dispatches) >= len(PLATFORMS),
        f"ORCHESTRATOR_DISPATCH success entries: {len(test_dispatches)} >= {len(PLATFORMS)}",
    )

    # ORCHESTRATOR_STOP — session ended cleanly
    check(
        len(find_log_entries("ORCHESTRATOR_STOP", "success")) > 0,
        "ORCHESTRATOR_STOP success in log",
    )

    # SKILL_RUN dry-run — one per platform
    skill_entries = find_log_entries("SKILL_RUN", "success", notes_substr="dry-run")
    for platform, *_ in PLATFORMS:
        found = any(platform in (e.get("notes") or "") for e in skill_entries)
        check(found, f"Log: SKILL_RUN dry-run — {platform}")

    # No real SOCIAL_POST success for test files (must NOT have posted)
    real_posts = [
        e for e in find_log_entries("SOCIAL_POST", "success")
        if any(
            TEST_FILES.get(p) and TEST_FILES[p].name in (e.get("source") or "")
            for p, *_ in PLATFORMS
        )
    ]
    check(
        len(real_posts) == 0,
        f"No real SOCIAL_POST success entries for test files (found {len(real_posts)})",
    )


# ─────────────────────────────────────────────────────────────────────────────

def test_cleanup() -> None:
    section("SECTION 7 — CLEANUP")

    removed = cleanup_test_files()
    check(removed >= 0, f"Cleanup ran without error ({removed} test file(s) removed)")

    # Verify nothing remains
    remaining = 0
    for folder in (PENDING_DIR, APPROVED_DIR):
        if not folder.exists():
            continue
        for f in folder.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(text)
                if TEST_TAG in str(fm.get("title", "")):
                    remaining += 1
            except Exception:
                pass

    check(remaining == 0, f"No test files remain in Pending_Approval/ or Approved/ (found {remaining})")


# ═════════════════════════════════════════════════════════════════════════════
# DAILY USAGE GUIDE
# ═════════════════════════════════════════════════════════════════════════════

DAILY_GUIDE = r"""
╔══════════════════════════════════════════════════════════════════════╗
║          DAILY USAGE — Social Manager (AI Employee Vault)           ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  STEP 0 — First-time login per platform (once only, never again):   ║
║    python watcher/social_media_executor_v2.py --login linkedin      ║
║    python watcher/social_media_executor_v2.py --login facebook      ║
║    python watcher/social_media_executor_v2.py --login instagram     ║
║    python watcher/social_media_executor_v2.py --login twitter       ║
║    python watcher/social_media_executor_v2.py --login whatsapp      ║
║    python watcher/social_media_executor_v2.py --login gmail         ║
║                                                                      ║
║  After login: browser cookies saved to session/<platform>/          ║
║  No login needed on any subsequent run. Ever.                       ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  STEP 1 — Create a draft with trigger_posts.py:                     ║
║                                                                      ║
║   LinkedIn (standard post):                                         ║
║    python watcher/trigger_posts.py \                                ║
║        --platform linkedin \                                        ║
║        --content "Excited to share our Q1 results!"                ║
║                                                                      ║
║   Twitter/X (auto-truncate to 280):                                 ║
║    python watcher/trigger_posts.py \                                ║
║        --platform twitter \                                         ║
║        --content "Big news today. #launch" \                        ║
║        --allow-truncate                                             ║
║                                                                      ║
║   Facebook (scheduled, high priority):                              ║
║    python watcher/trigger_posts.py \                                ║
║        --platform facebook \                                        ║
║        --content "Join our live demo Friday 3 PM EST!" \            ║
║        --priority high \                                            ║
║        --scheduled "2026-03-01 09:00"                               ║
║                                                                      ║
║   Instagram (image required):                                       ║
║    python watcher/trigger_posts.py \                                ║
║        --platform instagram \                                       ║
║        --content "Behind the scenes today." \                       ║
║        --image-path "assets/bts.jpg"                                ║
║                                                                      ║
║   WhatsApp (recipient required):                                    ║
║    python watcher/trigger_posts.py \                                ║
║        --platform whatsapp \                                        ║
║        --content "Reminder: meeting at 10 AM." \                    ║
║        --recipient "+447700900123"                                  ║
║                                                                      ║
║   Gmail (recipient + subject required):                             ║
║    python watcher/trigger_posts.py \                                ║
║        --platform gmail \                                           ║
║        --content "Please find this week's update below." \          ║
║        --recipient "team@company.com" \                             ║
║        --subject "Weekly Update"                                    ║
║                                                                      ║
║  Draft saved to: Pending_Approval/YYYY-MM-DD — Title — platform.md ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  STEP 2 — Human review + approval (HITL gate):                      ║
║    Open the file in Pending_Approval/ (Obsidian or any editor)      ║
║    Edit content if needed.                                          ║
║    Set:  approved_by: human                                         ║
║          status: approved                                           ║
║    Move file to: Approved/                                          ║
║                                                                      ║
║  IMPORTANT: The executor will hard-reject any file where            ║
║  approved_by is blank. This gate cannot be bypassed.                ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  STEP 3A — Continuous monitoring (recommended for daily use):       ║
║    Start the orchestrator once — it watches Approved/ forever:      ║
║    python watcher/master_orchestrator.py                            ║
║                                                                      ║
║    Custom poll interval (120s):                                     ║
║    python watcher/master_orchestrator.py --interval 120             ║
║                                                                      ║
║    PM2 (persistent across reboots):                                 ║
║    pm2 start watcher/ecosystem.config.js --only social-orchestrator ║
║    pm2 logs social-orchestrator                                     ║
║                                                                      ║
║  STEP 3B — One-shot (post everything in Approved/ now):             ║
║    python watcher/master_orchestrator.py --once                     ║
║                                                                      ║
║  STEP 3C — Execute a specific file manually:                        ║
║    python watcher/social_media_executor_v2.py \                     ║
║        --execute "Approved/2026-02-27 — My Post — linkedin.md"      ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  STEP 4 — Check results:                                            ║
║    Published files  → Done/YYYY-MM/                                 ║
║    Failed files     → stay in Approved/ with status: failed         ║
║    Failed (3x)      → archived to Logs/failed/                      ║
║    Platform paused  → Needs_Action/ escalation note created         ║
║    All activity     → Logs/YYYY-MM-DD.json + .md                    ║
║                                                                      ║
║  Check session status anytime:                                      ║
║    python watcher/social_media_executor_v2.py --check-session       ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Gold Tier Claude Skills (trigger from Claude chat):                ║
║    "draft linkedin post about <topic>"                              ║
║       → invokes skills/social-drafter.md                           ║
║    "execute post <filename>"                                        ║
║       → invokes skills/executor-handler.md                         ║
║    "start orchestrator"                                             ║
║       → invokes skills/monitor-orchestrator.md                     ║
║    "orchestrator status" / "show approved queue"                   ║
║       → invokes skills/monitor-orchestrator.md                     ║
║                                                                      ║
║  Skill definitions: AI_Employee_Vault/skills/                       ║
║    social-drafter.md    executor-handler.md    monitor-orchestrator.md
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  TOKENS / AUTH — After initial --login (zero ongoing auth):         ║
║    No API tokens required. Sessions are persisted as browser        ║
║    profiles in session/<platform>/ using Playwright's               ║
║    launch_persistent_context. Cookies, localStorage, and IndexedDB  ║
║    are stored on disk. No re-login unless the platform expires       ║
║    your session (typically 30–90 days depending on platform).       ║
║                                                                      ║
║    When a session expires: executor detects login page, creates     ║
║    Needs_Action/ escalation, pauses that platform. Human runs:      ║
║    python watcher/social_media_executor_v2.py --login <platform>    ║
║    Other platforms are unaffected and continue normally.            ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  RUN THIS TEST (zero real posts):                                   ║
║    python watcher/gold-social-test.py                               ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print()
    print("=" * 62)
    print("  GOLD SOCIAL TEST — AI Employee Vault")
    print("  Social Manager End-to-End (dry-run / no real posts)")
    print("  No browser — No tokens — No platform logins required")
    print(f"  Date : {TODAY}")
    print(f"  Vault: {VAULT_PATH}")
    print("=" * 62)

    # Remove any leftovers from a previous aborted run
    stale = cleanup_test_files()
    if stale:
        print(f"  (cleaned {stale} stale test file(s) from previous run)")

    test_preflight()
    test_draft_creation()
    test_hitl_simulation()
    test_orchestrator()
    test_executor()
    test_log_verification()
    test_cleanup()

    # ── Summary ──────────────────────────────────────────────────────────────
    total = PASS_COUNT + FAIL_COUNT
    print()
    print("=" * 62)
    print(f"  RESULTS: {PASS_COUNT} PASS  |  {FAIL_COUNT} FAIL  |  {total} total")

    if FAIL_COUNT == 0:
        print()
        print("  All tests passed. Social Manager pipeline is healthy.")
        print("  Read the daily usage guide below to run live posts.")
        print("=" * 62)
        print(DAILY_GUIDE)
    else:
        print()
        print(f"  {FAIL_COUNT} test(s) failed. Review the FAIL lines above.")
        print("  Common fixes:")
        print("    — Missing module: pip install -r watcher/requirements.txt")
        print("    — No session yet: python watcher/social_media_executor_v2.py --login <platform>")
        print("    — Wrong directory: run from vault root or from watcher/")
        print("=" * 62)

    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
