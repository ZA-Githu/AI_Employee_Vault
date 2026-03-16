"""
filesystem_watcher.py
---------------------
Concrete Bronze Tier watcher using the watchdog library.

Monitors Inbox/ for new .md files.
When a file appears:
  1. Reads the file content
  2. Injects required Needs_Action frontmatter
  3. Writes it to Needs_Action/
  4. Removes the original from Inbox/
  5. Appends a TRIAGE entry to Logs/YYYY-MM-DD.md

Run:
    python filesystem_watcher.py
    python filesystem_watcher.py --dry-run
"""

import sys
import time
import shutil
import argparse
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from base_watcher import BaseWatcher


# ──────────────────────────────────────────────────────────────
# Watchdog event handler
# ──────────────────────────────────────────────────────────────

class InboxEventHandler(FileSystemEventHandler):
    """Handles filesystem events inside Inbox/."""

    def __init__(self, watcher: "FileSystemWatcher"):
        super().__init__()
        self.watcher = watcher

    def on_created(self, event) -> None:
        """Triggered when a new file or directory is created in Inbox/."""
        if event.is_directory:
            return

        source = Path(event.src_path)

        # Only process markdown files
        if source.suffix.lower() != ".md":
            self.watcher.logger.debug(f"Skipped non-markdown file: {source.name}")
            return

        # Small delay to allow the file to finish writing before we read it
        time.sleep(0.5)

        self.watcher.process_file(source)

    def on_moved(self, event) -> None:
        """Treat a file moved INTO Inbox/ the same as a new file."""
        if event.is_directory:
            return
        dest = Path(event.dest_path)
        if dest.parent.resolve() == self.watcher.inbox_path.resolve():
            if dest.suffix.lower() == ".md":
                time.sleep(0.5)
                self.watcher.process_file(dest)


# ──────────────────────────────────────────────────────────────
# Main watcher
# ──────────────────────────────────────────────────────────────

class FileSystemWatcher(BaseWatcher):
    """
    Watches Inbox/ continuously.
    Moves new .md files to Needs_Action/ with injected frontmatter.
    """

    def __init__(self):
        super().__init__()
        self.observer: Observer | None = None 
        self._running: bool = False
        self._processed_count: int = 0
        self._error_count: int = 0
        self._start_time: datetime | None = None

    # ------------------------------------------------------------------
    # File processing
    # ------------------------------------------------------------------

    def _build_frontmatter(self, source_path: Path, existing_body: str) -> str:
        """
        Build a complete Needs_Action frontmatter block.
        Preserves the original body content unchanged.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Derive a clean title from the filename
        title = (
            source_path.stem
            .replace("—", " ")
            .replace("-", " ")
            .replace("_", " ")
            .strip()
        )

        return (
            f"---\n"
            f"title: \"{title}\"\n"
            f"status: pending\n"
            f"priority: medium\n"
            f"created: {today}\n"
            f"due: {today}\n"
            f"source: inbox\n"
            f"received_at: \"{now}\"\n"
            f"processed_by: filesystem_watcher\n"
            f"tags: [action, agent, inbox]\n"
            f"agent_assigned: claude\n"
            f"---\n\n"
            f"{existing_body.strip()}\n"
        )

    def _strip_existing_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter block from content if present."""
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
        return content

    def _resolve_destination(self, filename: str) -> Path:
        """
        Return a destination path in Needs_Action/.
        Appends a timestamp suffix if the filename already exists.
        """
        dest = self.needs_action_path / filename
        if dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            ts = datetime.now().strftime("%H%M%S")
            dest = self.needs_action_path / f"{stem}-{ts}{suffix}"
            self.logger.warning(f"Name collision — renamed to: {dest.name}")
        return dest

    def process_file(self, source_path: Path) -> None:
        """
        Process one file from Inbox/ → Needs_Action/.

        Steps:
          1. Read file content
          2. Strip any existing frontmatter
          3. Inject Needs_Action frontmatter
          4. Write to Needs_Action/
          5. Delete from Inbox/
          6. Log the TRIAGE action
        """
        filename = source_path.name
        self.logger.info(f"New file detected: {filename}")

        # ── Step 1: Read ──
        try:
            raw_content = source_path.read_text(encoding="utf-8")
        except Exception as exc:
            self.logger.error(f"Cannot read '{filename}': {exc}")
            self.log_to_vault(
                "ERROR",
                self.relative(source_path),
                notes=f"Cannot read file: {exc}",
                outcome="failed",
            )
            self._error_count += 1
            return

        # ── Step 2 & 3: Build new content ──
        body        = self._strip_existing_frontmatter(raw_content)
        new_content = self._build_frontmatter(source_path, body)

        # ── Step 4: Resolve destination ──
        dest_path = self._resolve_destination(filename)

        if self.dry_run:
            self.logger.info(
                f"[DRY-RUN] Would move: Inbox/{filename} → Needs_Action/{dest_path.name}"
            )
            self.log_to_vault(
                "TRIAGE",
                f"Inbox/{filename}",
                f"Needs_Action/{dest_path.name}",
                notes="dry-run — no files moved",
            )
            return

        # ── Step 5: Write + delete ──
        try:
            dest_path.write_text(new_content, encoding="utf-8")
            source_path.unlink()
        except Exception as exc:
            self.logger.error(f"Failed to move '{filename}': {exc}")
            self.log_to_vault(
                "ERROR",
                f"Inbox/{filename}",
                notes=f"Move failed: {exc}",
                outcome="failed",
            )
            self._error_count += 1
            # If the destination was written but source delete failed, clean up
            if dest_path.exists() and source_path.exists():
                dest_path.unlink()
                self.logger.debug("Rolled back partial write.")
            return

        # ── Step 6: Log ──
        self._processed_count += 1
        self.logger.info(f"✅ Moved to Needs_Action/{dest_path.name}")
        self.log_to_vault(
            "TRIAGE",
            f"Inbox/{filename}",
            f"Needs_Action/{dest_path.name}",
            notes="Auto-processed by filesystem_watcher",
        )

    # ------------------------------------------------------------------
    # Watcher lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching Inbox/ and block until Ctrl+C."""
        self.ensure_folders()
        self.print_banner()

        self._start_time = datetime.now()

        # Log startup
        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/watcher-management.md",
            notes=(
                f"FileSystemWatcher started — "
                f"dry_run={self.dry_run}"
            ),
        )

        # Set up watchdog observer
        event_handler = InboxEventHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.inbox_path), recursive=False)
        self.observer.start()
        self._running = True

        self.logger.info("Watcher active. Press Ctrl+C to stop.\n")

        try:
            while self._running:
                time.sleep(1)
                if not self.observer.is_alive():
                    self.logger.error("Observer thread died unexpectedly.")
                    break
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the observer and print session summary."""
        self._running = False

        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()

        duration = ""
        if self._start_time:
            secs    = int((datetime.now() - self._start_time).total_seconds())
            minutes = secs // 60
            seconds = secs % 60
            duration = f"{minutes}m {seconds}s"

        # Print summary
        print()
        print("=" * 60)
        print("  Watcher stopped.")
        print(f"  Session duration : {duration}")
        print(f"  Files processed  : {self._processed_count}")
        print(f"  Errors           : {self._error_count}")
        print("=" * 60)
        print()

        self.log_to_vault(
            "SKILL_RUN",
            ".claude/skills/watcher-management.md",
            notes=(
                f"FileSystemWatcher stopped — "
                f"duration: {duration}, "
                f"processed: {self._processed_count}, "
                f"errors: {self._error_count}"
            ),
        )


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Employee Vault — Bronze Tier File System Watcher"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect files but do not move them (overrides .env DRY_RUN setting)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # CLI --dry-run overrides the .env value
    if args.dry_run:
        import os
        os.environ["DRY_RUN"] = "true"

    watcher = FileSystemWatcher()
    watcher.start()
