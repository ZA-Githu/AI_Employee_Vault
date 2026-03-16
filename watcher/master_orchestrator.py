"""
master_orchestrator.py
----------------------
Gold Tier — Social Media Manager Orchestrator

Continuously monitors Approved/ using watchdog filesystem events.
When a new approved .md file appears, triggers social_media_executor_v2.py
as a subprocess to execute it.

Retry policy:
  - Up to 3 attempts per file, with RETRY_DELAY_S between each
  - After 3 failures: file archived to Logs/failed/ with error metadata

Cooldown:
  - After 3 consecutive failures on the same platform, that platform
    is paused for PLATFORM_COOLDOWN_S (default: 5 min)
  - Other platforms continue unaffected

Integrates with:
  - skills/monitor-orchestrator.md   (skill definition)
  - watcher/social_media_executor_v2.py  (called as subprocess per post)
  - watcher/audit_logger.py          (structured JSON + MD logging)

Run:
  python master_orchestrator.py                   # continuous watch loop
  python master_orchestrator.py --once            # scan Approved/ once, then exit
  python master_orchestrator.py --dry-run         # validate files, no execution
  python master_orchestrator.py --platform linkedin  # one platform only
  python master_orchestrator.py --interval 120    # custom poll interval (seconds)
"""

import os
import re
import sys
import time
import json
import yaml
import signal
import logging
import argparse
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Sibling imports
sys.path.insert(0, str(Path(__file__).parent))
from audit_logger import AuditLogger

# ── Windows UTF-8 output ───────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────
VAULT_PATH       = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
EXECUTOR_SCRIPT  = Path(__file__).parent / "social_media_executor_v2.py"

APPROVED_PATH    = VAULT_PATH / "Approved"
DONE_PATH        = VAULT_PATH / "Done"
LOGS_PATH        = VAULT_PATH / "Logs"
FAILED_PATH      = LOGS_PATH / "failed"
NEEDS_ACTION     = VAULT_PATH / "Needs_Action"

DRY_RUN              = os.getenv("DRY_RUN",              "false").lower() == "true"
MAX_RETRIES          = int(os.getenv("MAX_RETRIES",      "3"))
RETRY_DELAY_S        = int(os.getenv("RETRY_DELAY_S",    "10"))
PLATFORM_COOLDOWN_S  = int(os.getenv("PLATFORM_COOLDOWN_S", "300"))   # 5 min
EXEC_TIMEOUT_S       = int(os.getenv("EXEC_TIMEOUT_S",   "300"))      # 5 min per post
POLL_INTERVAL_S      = int(os.getenv("ORCHESTRATOR_INTERVAL", "60"))

SUPPORTED_PLATFORMS = ["facebook", "instagram", "linkedin", "twitter", "whatsapp", "gmail"]

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)-8s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MasterOrchestrator")


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
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body


def is_eligible(path: Path, platform_filter: "str | None") -> "tuple[bool, dict]":
    """
    Return (eligible, frontmatter).
    A file is eligible if:
      - It is a .md file
      - type == social-post
      - approved_by is non-empty
      - status == approved
      - published is not set
      - failed_at is not set  (already failed — needs human reset)
      - platform matches filter (if set)
    """
    if path.suffix.lower() != ".md":
        return False, {}
    try:
        text     = path.read_text(encoding="utf-8")
        fm, _    = parse_frontmatter(text)
    except Exception:
        return False, {}

    if fm.get("type") != "social-post":
        return False, fm
    if not fm.get("approved_by"):
        return False, fm
    if fm.get("status") != "approved":
        return False, fm
    if fm.get("published"):
        return False, fm
    if fm.get("failed_at"):
        return False, fm   # needs human to reset status before retry
    if platform_filter and fm.get("platform") != platform_filter:
        return False, fm

    return True, fm


def archive_failed(plan_path: Path, fm: dict, body: str, error: str, attempt: int) -> Path:
    """
    Move exhausted file from Approved/ to Logs/failed/ with error metadata.
    Returns destination path.
    """
    FAILED_PATH.mkdir(parents=True, exist_ok=True)

    fm["status"]            = "failed"
    fm["failed_at"]         = datetime.now().strftime("%Y-%m-%d %H:%M")
    fm["failed_attempts"]   = attempt
    fm["error"]             = error[:300]
    fm["archived_to"]       = "Logs/failed/"

    dest = FAILED_PATH / plan_path.name
    # Avoid clobbering if name already exists
    if dest.exists():
        stem = plan_path.stem
        ext  = plan_path.suffix
        ts   = datetime.now().strftime("%H%M%S")
        dest = FAILED_PATH / f"{stem}-{ts}{ext}"

    dest.write_text(write_frontmatter(fm, body), encoding="utf-8")
    plan_path.unlink(missing_ok=True)
    return dest


def create_escalation_note(platform: str, count: int, last_error: str) -> None:
    """Write a Needs_Action/ escalation note after 3 consecutive platform failures."""
    NEEDS_ACTION.mkdir(parents=True, exist_ok=True)
    now      = datetime.now()
    filename = f"{now.strftime('%Y-%m-%d %H-%M')} — Orchestrator-Failure-{platform}.md"
    path     = NEEDS_ACTION / filename
    content  = (
        f"---\n"
        f"title: \"Orchestrator: {platform} paused after {count} consecutive failures\"\n"
        f"type: escalation\n"
        f"skill: master-orchestrator\n"
        f"error_level: L3\n"
        f"platform: {platform}\n"
        f"failures: {count}\n"
        f"error: \"{last_error[:150].replace(chr(34), chr(39))}\"\n"
        f"action_required: \"Check session/{platform}/ — re-authenticate if needed. "
        f"Reset failed posts in Logs/failed/ to status: approved to retry.\"\n"
        f"status: pending\n"
        f"priority: high\n"
        f"created: {now.strftime('%Y-%m-%d')}\n"
        f"tags: [escalation, orchestrator, {platform}]\n"
        f"---\n\n"
        f"# Orchestrator Escalation: {platform}\n\n"
        f"**Platform** `{platform}` paused after **{count} consecutive failures**.\n\n"
        f"**Last error:**\n```\n{last_error[:400]}\n```\n\n"
        f"## Action Required\n\n"
        f"1. Check `session/{platform}/` — re-authenticate if the session expired.\n"
        f"2. Review failed posts in `Logs/failed/`.\n"
        f"3. To retry a post: copy it back to `Approved/`, reset `status: approved`, "
        f"remove `failed_at:` line.\n"
        f"4. Platform will resume automatically on next orchestrator restart.\n"
    )
    path.write_text(content, encoding="utf-8")
    logger.warning(f"Escalation note created: Needs_Action/{filename}")


# ── Retry tracker ─────────────────────────────────────────────

class RetryTracker:
    """Thread-safe per-file retry counter."""

    def __init__(self):
        self._lock    = threading.Lock()
        self._counts: dict[str, int]   = {}   # filepath → attempt count
        self._pending: dict[str, float] = {}  # filepath → next_attempt_time

    def get(self, path: Path) -> int:
        with self._lock:
            return self._counts.get(str(path), 0)

    def increment(self, path: Path) -> int:
        with self._lock:
            key = str(path)
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def schedule_retry(self, path: Path, delay_s: float) -> None:
        with self._lock:
            self._pending[str(path)] = time.monotonic() + delay_s

    def is_ready(self, path: Path) -> bool:
        with self._lock:
            due = self._pending.get(str(path), 0)
            return time.monotonic() >= due

    def clear(self, path: Path) -> None:
        with self._lock:
            key = str(path)
            self._counts.pop(key, None)
            self._pending.pop(key, None)


# ── Platform cooldown tracker ─────────────────────────────────

class CooldownTracker:
    """Tracks consecutive failures per platform and enforces cooldown."""

    def __init__(self):
        self._lock            = threading.Lock()
        self._consec: dict[str, int]   = defaultdict(int)
        self._cooldown: dict[str, float] = {}   # platform → resume_time
        self._last_error: dict[str, str] = {}

    def record_failure(self, platform: str, error: str) -> bool:
        """
        Increment failure count. Returns True if cooldown was just triggered.
        """
        with self._lock:
            self._consec[platform]     += 1
            self._last_error[platform]  = error
            if self._consec[platform] >= MAX_RETRIES:
                self._cooldown[platform] = time.monotonic() + PLATFORM_COOLDOWN_S
                return True
        return False

    def record_success(self, platform: str) -> None:
        with self._lock:
            self._consec[platform]    = 0
            self._cooldown.pop(platform, None)

    def is_paused(self, platform: str) -> bool:
        with self._lock:
            due = self._cooldown.get(platform, 0)
            if time.monotonic() < due:
                return True
            if platform in self._cooldown:
                # Cooldown expired — reset
                del self._cooldown[platform]
                self._consec[platform] = 0
            return False

    def resume_time(self, platform: str) -> str:
        with self._lock:
            due = self._cooldown.get(platform, 0)
            remaining = max(0, due - time.monotonic())
            return f"{int(remaining)}s"

    def last_error(self, platform: str) -> str:
        with self._lock:
            return self._last_error.get(platform, "")

    def consec(self, platform: str) -> int:
        with self._lock:
            return self._consec.get(platform, 0)


# ── Watchdog handler ──────────────────────────────────────────

class ApprovedFolderHandler(FileSystemEventHandler):
    """
    Watchdog event handler for Approved/.
    Notifies MasterOrchestrator when a new .md file appears.
    """

    def __init__(self, orchestrator: "MasterOrchestrator"):
        super().__init__()
        self.orchestrator = orchestrator

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() == ".md":
            logger.info(f"Watchdog: new file detected → {path.name}")
            # Brief settle delay — let the file finish writing
            time.sleep(1.5)
            self.orchestrator.enqueue(path)

    def on_moved(self, event):
        """Handle files moved/renamed into Approved/."""
        if event.is_directory:
            return
        dest = Path(event.dest_path)
        if dest.parent.resolve() == APPROVED_PATH.resolve() and dest.suffix.lower() == ".md":
            logger.info(f"Watchdog: file moved in → {dest.name}")
            time.sleep(1.5)
            self.orchestrator.enqueue(dest)


# ── Master Orchestrator ───────────────────────────────────────

class MasterOrchestrator:
    """
    Monitors Approved/ for new approved social posts and executes them
    via social_media_executor_v2.py subprocess.

    Execution is serial: one post at a time, waiting for completion
    before picking up the next.
    """

    def __init__(
        self,
        platform_filter: "str | None" = None,
        poll_interval: int = POLL_INTERVAL_S,
        once: bool = False,
    ):
        self.platform_filter  = platform_filter
        self.poll_interval    = poll_interval
        self.once             = once

        self.audit            = AuditLogger(VAULT_PATH)
        self.retries          = RetryTracker()
        self.cooldowns        = CooldownTracker()

        self._stop_event      = threading.Event()
        self._queue_lock      = threading.Lock()
        self._queue: list[Path] = []

        self._posts_success   = 0
        self._posts_failed    = 0
        self._start_time: "datetime | None" = None

        # Register SIGINT for clean shutdown
        signal.signal(signal.SIGINT, self._handle_sigint)

    def _handle_sigint(self, sig, frame) -> None:
        logger.info("Ctrl+C received — stopping orchestrator after current post ...")
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def enqueue(self, path: Path) -> None:
        """Add a path to the processing queue (thread-safe)."""
        eligible, fm = is_eligible(path, self.platform_filter)
        if not eligible:
            return
        with self._queue_lock:
            if path not in self._queue:
                self._queue.append(path)
                logger.info(f"Queued: {path.name} (platform: {fm.get('platform', '?')})")

    def _dequeue_ready(self) -> "Path | None":
        """Return the next path that is ready to process (not pending retry delay)."""
        with self._queue_lock:
            priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            eligible = []
            for p in list(self._queue):
                if not p.exists():
                    self._queue.remove(p)
                    continue
                if not self.retries.is_ready(p):
                    continue
                try:
                    fm, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
                    prio  = priority_order.get(fm.get("priority", "medium"), 2)
                    eligible.append((prio, p.stat().st_mtime, p))
                except Exception:
                    eligible.append((2, 0, p))

            if not eligible:
                return None
            eligible.sort(key=lambda x: (x[0], x[1]))
            chosen = eligible[0][2]
            self._queue.remove(chosen)
            return chosen

    def _scan_approved(self) -> None:
        """Scan Approved/ and enqueue all eligible files (startup + periodic)."""
        if not APPROVED_PATH.exists():
            return
        for f in sorted(APPROVED_PATH.glob("*.md"), key=lambda x: x.stat().st_mtime):
            self.enqueue(f)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _run_executor(self, plan_path: Path) -> "tuple[bool, str]":
        """
        Call social_media_executor_v2.py --execute <file> as a subprocess.
        Returns (success, error_message).
        """
        if DRY_RUN:
            logger.info(f"[DRY-RUN] Would execute: {plan_path.name}")
            return True, ""

        cmd = [
            sys.executable,
            str(EXECUTOR_SCRIPT),
            "--execute",
            str(plan_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT_S,
                cwd=str(VAULT_PATH),
            )
            if result.stdout:
                for line in result.stdout.splitlines()[-20:]:  # last 20 lines
                    logger.info(f"  [exec] {line}")
            if result.returncode == 0:
                return True, ""
            else:
                err = (result.stderr or result.stdout or "executor exited non-zero").strip()
                return False, err[-400:]
        except subprocess.TimeoutExpired:
            return False, f"Executor timed out after {EXEC_TIMEOUT_S}s"
        except Exception as exc:
            return False, str(exc)

    def _process(self, plan_path: Path) -> None:
        """
        Process one file: run executor, handle retry / archive on failure.
        """
        if not plan_path.exists():
            logger.warning(f"File no longer exists: {plan_path.name} — skipping")
            self.retries.clear(plan_path)
            return

        eligible, fm = is_eligible(plan_path, self.platform_filter)
        if not eligible:
            logger.debug(f"Skipping (not eligible): {plan_path.name}")
            self.retries.clear(plan_path)
            return

        platform = fm.get("platform", "unknown")
        attempt  = self.retries.get(plan_path) + 1

        # Platform cooldown check
        if self.cooldowns.is_paused(platform):
            remaining = self.cooldowns.resume_time(platform)
            logger.warning(
                f"Platform '{platform}' is in cooldown ({remaining} remaining) — "
                f"re-queuing {plan_path.name}"
            )
            with self._queue_lock:
                if plan_path not in self._queue:
                    self._queue.append(plan_path)
            return

        logger.info(f"Processing [{attempt}/{MAX_RETRIES}]: {plan_path.name} (platform: {platform})")

        self.audit.log_action(
            "ORCHESTRATOR_DISPATCH", "master-orchestrator",
            f"Approved/{plan_path.name}", "social_media_executor_v2.py",
            notes=f"platform: {platform} | attempt: {attempt}",
        )

        success, error = self._run_executor(plan_path)

        if success:
            logger.info(f"SUCCESS: {plan_path.name}")
            self.retries.clear(plan_path)
            self.cooldowns.record_success(platform)
            self._posts_success += 1
            self.audit.log_action(
                "ORCHESTRATOR_DISPATCH", "master-orchestrator",
                f"Approved/{plan_path.name}",
                f"Done/",
                "success",
                notes=f"platform: {platform} | attempt: {attempt}",
            )
            return

        # Failure path
        self.retries.increment(plan_path)
        actual_attempt = self.retries.get(plan_path)
        triggered      = self.cooldowns.record_failure(platform, error)

        logger.warning(
            f"FAILED [{actual_attempt}/{MAX_RETRIES}]: {plan_path.name} — {error[:120]}"
        )

        if actual_attempt < MAX_RETRIES:
            # Schedule retry
            self.retries.schedule_retry(plan_path, RETRY_DELAY_S)
            logger.info(f"Retry scheduled in {RETRY_DELAY_S}s: {plan_path.name}")
            with self._queue_lock:
                if plan_path not in self._queue:
                    self._queue.append(plan_path)
            self.audit.log_action(
                "ORCHESTRATOR_FAILURE", "master-orchestrator",
                f"Approved/{plan_path.name}", None, "failed",
                notes=f"platform: {platform} | attempt: {actual_attempt} | retry_in: {RETRY_DELAY_S}s | error: {error[:100]}",
            )
        else:
            # All retries exhausted — archive to Logs/failed/
            try:
                text     = plan_path.read_text(encoding="utf-8")
                fm2, body = parse_frontmatter(text)
            except Exception:
                fm2, body = fm, ""

            dest = archive_failed(plan_path, fm2, body, error, actual_attempt)
            self._posts_failed += 1
            self.retries.clear(plan_path)

            logger.error(
                f"EXHAUSTED ({actual_attempt} attempts): {plan_path.name} — "
                f"archived to Logs/failed/{dest.name}"
            )

            self.audit.log_action(
                "ORCHESTRATOR_FAILURE", "master-orchestrator",
                f"Approved/{plan_path.name}",
                f"Logs/failed/{dest.name}",
                "failed",
                notes=f"platform: {platform} | attempts: {actual_attempt} | error: {error[:100]}",
                error={"message": error[:200], "level": "L3", "recovery_action": "manual_retry"},
            )

            # Platform cooldown escalation
            if triggered:
                logger.error(
                    f"Platform '{platform}' paused for {PLATFORM_COOLDOWN_S}s "
                    f"after {MAX_RETRIES} consecutive failures."
                )
                create_escalation_note(
                    platform,
                    self.cooldowns.consec(platform),
                    self.cooldowns.last_error(platform),
                )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the orchestrator — watchdog + poll loop."""
        self._start_time = datetime.now()
        self._print_banner()

        APPROVED_PATH.mkdir(parents=True, exist_ok=True)
        FAILED_PATH.mkdir(parents=True, exist_ok=True)
        LOGS_PATH.mkdir(parents=True, exist_ok=True)

        self.audit.log_action(
            "ORCHESTRATOR_START", "master-orchestrator",
            "Approved/", None, "success",
            notes=(
                f"interval: {self.poll_interval}s | "
                f"once: {self.once} | "
                f"dry_run: {DRY_RUN} | "
                f"platform: {self.platform_filter or 'all'}"
            ),
        )

        # Initial scan on startup
        logger.info("Initial scan of Approved/ ...")
        self._scan_approved()

        if self.once:
            self._run_once()
            return

        # Start watchdog observer
        handler  = ApprovedFolderHandler(self)
        observer = Observer()
        observer.schedule(handler, str(APPROVED_PATH), recursive=False)
        observer.start()
        logger.info(f"Watchdog active — watching: {APPROVED_PATH}")
        logger.info(f"Poll fallback every {self.poll_interval}s. Ctrl+C to stop.")
        logger.info("")

        poll_cycle = 0
        try:
            while not self._stop_event.is_set():
                poll_cycle += 1

                # Process whatever is in the queue
                while not self._stop_event.is_set():
                    next_file = self._dequeue_ready()
                    if next_file is None:
                        break
                    self._process(next_file)
                    time.sleep(5)   # rate-limit between consecutive posts

                # Periodic poll (catches anything watchdog might miss)
                self.audit.log_action(
                    "ORCHESTRATOR_POLL", "master-orchestrator",
                    "Approved/", None, "success",
                    notes=f"cycle: {poll_cycle} | queue: {len(self._queue)}",
                )

                self._scan_approved()   # re-scan for anything new

                # Wait for next cycle (interruptible)
                for _ in range(self.poll_interval):
                    if self._stop_event.is_set():
                        break
                    time.sleep(1)

        finally:
            observer.stop()
            observer.join()
            self._shutdown()

    def _run_once(self) -> None:
        """Process everything currently in the queue, then exit."""
        logger.info("One-shot mode: processing current Approved/ queue ...")
        while True:
            next_file = self._dequeue_ready()
            if next_file is None:
                break
            self._process(next_file)
            time.sleep(5)
        self._shutdown()

    def _shutdown(self) -> None:
        duration = ""
        if self._start_time:
            secs     = int((datetime.now() - self._start_time).total_seconds())
            duration = f"{secs // 60}m {secs % 60}s"

        self.audit.log_action(
            "ORCHESTRATOR_STOP", "master-orchestrator",
            "Approved/", None, "success",
            notes=(
                f"published: {self._posts_success} | "
                f"failed: {self._posts_failed} | "
                f"duration: {duration}"
            ),
        )

        print()
        print("=" * 60)
        print("  Master Orchestrator stopped.")
        print(f"  Duration   : {duration}")
        print(f"  Published  : {self._posts_success}")
        print(f"  Failed     : {self._posts_failed}")
        print(f"  Archived   : Logs/failed/")
        print("=" * 60)
        print()

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def _print_banner(self) -> None:
        mode_str = "DRY-RUN" if DRY_RUN else "LIVE"
        mode_run = "ONE-SHOT" if self.once else "CONTINUOUS"
        print()
        print("=" * 60)
        print("  AI Employee Vault — Master Orchestrator")
        print("  Gold Tier | Social Manager Extension")
        print(f"  Mode       : {mode_str} | {mode_run}")
        print(f"  Platform   : {self.platform_filter or 'all platforms'}")
        print(f"  Interval   : {self.poll_interval}s")
        print(f"  Max retries: {MAX_RETRIES} per file")
        print(f"  Cooldown   : {PLATFORM_COOLDOWN_S}s per platform after {MAX_RETRIES} failures")
        print(f"  Watching   : {APPROVED_PATH}")
        print(f"  Vault      : {VAULT_PATH}")
        print("=" * 60)
        print()


# ── CLI ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Master Orchestrator — watch Approved/ and execute social posts",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Process all current Approved/ files once, then exit",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files and log — no executor called",
    )
    p.add_argument(
        "--platform",
        metavar="PLATFORM",
        default=None,
        help="Only process files for this platform",
    )
    p.add_argument(
        "--interval",
        metavar="SECONDS",
        type=int,
        default=POLL_INTERVAL_S,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL_S})",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.dry_run:
        DRY_RUN = True
        os.environ["DRY_RUN"] = "true"

    if args.platform and args.platform not in SUPPORTED_PLATFORMS:
        print(f"[ERROR] Unknown platform: {args.platform}")
        print(f"  Supported: {', '.join(SUPPORTED_PLATFORMS)}")
        sys.exit(1)

    orchestrator = MasterOrchestrator(
        platform_filter=args.platform,
        poll_interval=args.interval,
        once=args.once,
    )
    orchestrator.start()
