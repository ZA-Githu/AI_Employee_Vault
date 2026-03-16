"""
base_watcher.py
---------------
Abstract base class for all Bronze Tier vault watchers.
Handles configuration, logging setup, vault log writing, and folder validation.
"""

import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class BaseWatcher(ABC):
    """
    Foundation class for vault watchers.
    Subclass this and implement start() and stop().
    """

    def __init__(self):
        self.vault_path      = Path(os.getenv("VAULT_PATH", str(Path(__file__).parent.parent))).resolve()
        self.inbox_path      = self.vault_path / os.getenv("INBOX_FOLDER",        "Inbox")
        self.needs_action_path = self.vault_path / os.getenv("NEEDS_ACTION_FOLDER", "Needs_Action")
        self.logs_path       = self.vault_path / os.getenv("LOGS_FOLDER",          "Logs")
        self.dry_run         = os.getenv("DRY_RUN", "false").lower() == "true"

        self._setup_logging()
        self._validate_vault()

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        """Configure console logging."""
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, log_level, logging.INFO)

        logging.basicConfig(
            level=level,
            format="%(asctime)s  [%(levelname)-8s]  %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Vault validation
    # ------------------------------------------------------------------

    def _validate_vault(self) -> None:
        """Warn if required vault folders are missing (they will be created on start)."""
        if not self.vault_path.exists():
            self.logger.warning(f"Vault path does not exist: {self.vault_path}")
        if not (self.vault_path / "Bronze-Constitution.md").exists():
            self.logger.warning("Bronze-Constitution.md not found — is this the correct vault?")

    def ensure_folders(self) -> None:
        """Create required vault folders if they do not exist."""
        for folder in [self.inbox_path, self.needs_action_path, self.logs_path]:
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"Created folder: {folder.relative_to(self.vault_path)}")

    # ------------------------------------------------------------------
    # Vault log writer
    # ------------------------------------------------------------------

    def log_to_vault(
        self,
        action_type: str,
        source: str,
        destination: str = "—",
        outcome: str = "success",
        notes: str = "",
    ) -> None:
        """
        Append one structured entry to today's Logs/YYYY-MM-DD.md file.

        action_type : CREATE | MOVE | EDIT | DELETE | SKILL_RUN | TRIAGE | CLOSE | ERROR
        source      : relative path of the file being acted on
        destination : relative path of destination (or "—" if not applicable)
        outcome     : "success" or "failed"
        notes       : one-sentence description
        """
        today     = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_file  = self.logs_path / f"{today}.md"

        dest_str     = f"`{destination}`" if destination != "—" else "—"
        outcome_icon = "✅" if outcome == "success" else "❌"

        entry = (
            f"- `{timestamp}` | **{action_type}** | "
            f"`{source}` → {dest_str} | "
            f"{outcome_icon} {outcome} | {notes}\n"
        )

        if self.dry_run:
            self.logger.info(f"[DRY-RUN] vault log skipped: {entry.strip()}")
            return

        # Create log file with header if it does not exist yet
        if not log_file.exists():
            self.logs_path.mkdir(parents=True, exist_ok=True)
            header = (
                f"---\n"
                f"title: \"Agent Log — {today}\"\n"
                f"date: {today}\n"
                f"tags: [log, agent, watcher]\n"
                f"---\n\n"
                f"# Agent Log — {today}\n\n"
                f"> Append-only. Do not edit existing entries.\n"
                f"> Format: `HH:MM:SS` | **ACTION** | `source` → `dest` | outcome | notes\n\n"
                f"---\n\n"
            )
            log_file.write_text(header, encoding="utf-8")
            self.logger.debug(f"Created log file: {log_file.name}")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def relative(self, path: Path) -> str:
        """Return a path string relative to the vault root."""
        try:
            return str(path.relative_to(self.vault_path))
        except ValueError:
            return str(path)

    def print_banner(self) -> None:
        """Print startup banner to console."""
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        print()
        print("=" * 60)
        print("  AI Employee Vault — File System Watcher")
        print("  Bronze Tier | Personal AI Employee Hackathon 2026")
        print(f"  Mode      : {mode}")
        print(f"  Vault     : {self.vault_path}")
        print(f"  Watching  : {self.inbox_path.name}/")
        print(f"  Routing to: {self.needs_action_path.name}/")
        print(f"  Logs      : {self.logs_path.name}/")
        print("=" * 60)
        print()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self) -> None:
        """Start the watcher. Must block until stop() is called."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the watcher cleanly."""
