"""
trigger_posts.py
----------------
Gold Tier — Social Manager Extension
Terminal-based draft generator. Implements skills/social-drafter.md.

Generates a properly-formatted .md draft file and saves it to
Pending_Approval/. Never posts — all execution happens after human
approval via executor-handler.md / master_orchestrator.py.

Supported platforms: facebook | instagram | linkedin | twitter | whatsapp | gmail

Usage:
    python trigger_posts.py --platform linkedin  --content "My new post"
    python trigger_posts.py --platform whatsapp  --content "Hey!" --recipient "+447700900123"
    python trigger_posts.py --platform gmail     --content "Body" --recipient "a@b.com" --subject "Hello"
    python trigger_posts.py --platform instagram --content "Caption" --image-path assets/photo.jpg
    python trigger_posts.py --platform twitter   --content "Short post" --allow-truncate
    python trigger_posts.py --platform facebook  --content "Long post" --priority high --scheduled "2026-03-01 09:00"
    python trigger_posts.py --dry-run --platform linkedin --content "Preview only"
"""

# ── stdout UTF-8 for Windows cp1252 ──────────────────────────────────────────
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import re
import argparse
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
WATCHER_DIR = Path(__file__).parent.resolve()
VAULT_PATH  = Path(os.getenv("VAULT_PATH", str(WATCHER_DIR.parent))).resolve()
sys.path.insert(0, str(WATCHER_DIR))

from audit_logger import AuditLogger

# ── Folder paths ──────────────────────────────────────────────────────────────
PENDING_DIR = VAULT_PATH / "Pending_Approval"
LOGS_DIR    = VAULT_PATH / "Logs"

# ── Platform config ───────────────────────────────────────────────────────────
SUPPORTED_PLATFORMS = frozenset({"facebook", "instagram", "linkedin", "twitter", "whatsapp", "gmail"})

# Character limits per skills/social-drafter.md
CHAR_LIMITS: dict[str, int | None] = {
    "twitter":   280,
    "instagram": 2_200,
    "linkedin":  3_000,
    "facebook":  63_206,
    "whatsapp":  65_536,
    "gmail":     None,    # soft warn at 10,000
}
GMAIL_SOFT_LIMIT = 10_000

SKILL_NAME = "skills/social-drafter"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_title(text: str, max_words: int = 6) -> str:
    """
    Build a human-readable post title from the first max_words words.
    Strips characters that are illegal in Windows filenames.
    """
    words = text.split()[:max_words]
    title = " ".join(words)
    if len(text.split()) > max_words:
        title += "..."
    # Strip characters illegal in Windows filenames
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()


def _build_filename(title: str, platform: str, date: str) -> str:
    """
    Filename format from social-drafter.md:
        YYYY-MM-DD — <Title> — <platform>.md
    Em-dash (—) used per vault convention.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    return f"{date} \u2014 {safe} \u2014 {platform}.md"


def _enforce_char_limit(
    content: str, platform: str, allow_truncate: bool
) -> tuple[str, list[str]]:
    """
    Enforce platform character limits per social-drafter.md.

    Returns (final_content, warning_messages).
    Calls sys.exit(1) on hard-reject.
    """
    warnings: list[str] = []
    count = len(content)
    limit = CHAR_LIMITS.get(platform)

    if platform == "gmail":
        if count > GMAIL_SOFT_LIMIT:
            warnings.append(
                f"[WARNING] Gmail content is {count:,} chars "
                f"(soft limit {GMAIL_SOFT_LIMIT:,}). Large emails may be clipped by clients."
            )
        return content, warnings

    if limit and count > limit:
        label = "Twitter/X" if platform == "twitter" else platform.capitalize()
        if platform == "twitter" and allow_truncate:
            content = content[:limit]
            warnings.append(
                f"[WARNING] Content truncated to {limit} chars for {label} "
                f"(--allow-truncate active). Original was {count} chars."
            )
        else:
            hint = " Use --allow-truncate to truncate automatically." if platform == "twitter" else ""
            print(
                f"\n[ERROR] Content is {count:,} chars \u2014 exceeds {label} limit of "
                f"{limit:,} chars. Please shorten your content and retry.{hint}\n",
                file=sys.stderr,
            )
            sys.exit(1)

    return content, warnings


def _validate_conditional_fields(
    platform: str, recipient: str, subject: str, image_path: str
) -> list[str]:
    """
    Warn (not hard-block) on missing conditional fields per social-drafter.md.
    WhatsApp/Gmail warn on missing recipient.
    Gmail warns on missing subject.
    Instagram warns on missing image_path.
    """
    warnings: list[str] = []
    if platform in ("whatsapp", "gmail") and not recipient:
        warnings.append(
            f"[WARNING] --recipient is missing for {platform}. Draft saved, "
            "but executor will require it before posting."
        )
    if platform == "gmail" and not subject:
        warnings.append(
            "[WARNING] --subject is missing for Gmail. Draft saved, "
            "but executor will require it before posting."
        )
    if platform == "instagram" and not image_path:
        warnings.append(
            "[WARNING] --image-path is missing for Instagram. Draft saved, "
            "but you should add an image path before posting."
        )
    return warnings


def _build_frontmatter(
    title: str,
    platform: str,
    recipient: str,
    subject: str,
    image_path: str,
    priority: str,
    scheduled: str,
    allow_truncate: bool,
    date: str,
) -> str:
    """
    Build YAML frontmatter exactly matching skills/social-drafter.md contract.
    approved_by is always blank — only a human may fill it.
    status is always 'pending'.
    """
    lines = [
        "---",
        f'title: "{title}"',
        f"platform: {platform}",
        "type: social-post",
        "status: pending",
        "approved_by:",
        f"created: {date}",
        f"priority: {priority}",
        f"scheduled: {scheduled}",
        f"image_path: {image_path}",
        f"recipient: {recipient}",
        f"subject: {subject}",
        f"allow_truncate: {'true' if allow_truncate else 'false'}",
        f"tags: [social, draft, {platform}]",
        "---",
    ]
    return "\n".join(lines)


def _build_draft(frontmatter: str, content: str) -> str:
    return f"{frontmatter}\n\n## Post Content\n\n{content}\n"


# ── Core function ─────────────────────────────────────────────────────────────

def create_draft(
    platform: str,
    content: str,
    recipient: str = "",
    subject: str = "",
    image_path: str = "",
    title: str = "",
    priority: str = "medium",
    scheduled: str = "",
    allow_truncate: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Generate a social post draft and save it to Pending_Approval/.
    Implements skills/social-drafter.md Step 1-9.
    """
    audit = AuditLogger(VAULT_PATH)
    date  = datetime.now().strftime("%Y-%m-%d")

    # Step 1 — Validate platform
    platform = platform.lower()
    if platform not in SUPPORTED_PLATFORMS:
        print(
            f"\n[ERROR] Unknown platform '{platform}'.\n"
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 2 — Enforce character limits (may truncate or exit)
    content, char_warnings = _enforce_char_limit(content, platform, allow_truncate)
    char_count = len(content)

    # Step 3 — Conditional field warnings
    field_warnings = _validate_conditional_fields(platform, recipient, subject, image_path)

    all_warnings = char_warnings + field_warnings
    for w in all_warnings:
        print(w)

    # Step 4 — Build title
    if not title:
        title = _safe_title(content)

    # Step 5 — Build file content
    frontmatter = _build_frontmatter(
        title         = title,
        platform      = platform,
        recipient     = recipient,
        subject       = subject,
        image_path    = image_path,
        priority      = priority,
        scheduled     = scheduled,
        allow_truncate= allow_truncate,
        date          = date,
    )
    draft_text = _build_draft(frontmatter, content)
    filename   = _build_filename(title, platform, date)
    dest_path  = PENDING_DIR / filename

    # ── Dry-run branch ────────────────────────────────────────────────────────
    if dry_run:
        print()
        print("=" * 62)
        print("  TRIGGER_POSTS  |  DRY-RUN  (no file written)")
        print("=" * 62)
        print(f"  Platform   : {platform}")
        print(f"  Title      : {title}")
        print(f"  Characters : {char_count:,}")
        print(f"  Filename   : {filename}")
        print(f"  Destination: Pending_Approval/ (not written)")
        print("=" * 62)
        print()
        print(draft_text)
        audit.log_action(
            "SKILL_RUN", SKILL_NAME, SKILL_NAME, None, "success",
            notes=f"dry-run | platform: {platform} | chars: {char_count}",
        )
        return

    # ── Write file ────────────────────────────────────────────────────────────
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting an existing draft with same name
    if dest_path.exists():
        ts        = datetime.now().strftime("%H%M%S")
        filename  = _build_filename(f"{title} {ts}", platform, date)
        dest_path = PENDING_DIR / filename

    dest_path.write_text(draft_text, encoding="utf-8")

    # ── Log DRAFT_CREATE ──────────────────────────────────────────────────────
    notes_parts = [f"platform: {platform}", f"chars: {char_count}"]
    if recipient:
        notes_parts.append(f"recipient: {recipient}")
    if subject:
        notes_parts.append(f"subject: {subject}")
    if any("recipient" in w for w in all_warnings):
        notes_parts.append("recipient: missing")

    audit.log_action(
        "DRAFT_CREATE",
        SKILL_NAME,
        SKILL_NAME,
        f"Pending_Approval/{filename}",
        "success",
        notes=" | ".join(notes_parts),
    )

    # ── Human confirmation ────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("  Draft created  |  Social Manager")
    print("=" * 62)
    print(f"  File       : Pending_Approval/{filename}")
    print(f"  Platform   : {platform}")
    print(f"  Characters : {char_count:,}")
    if recipient:
        print(f"  Recipient  : {recipient}")
    if subject:
        print(f"  Subject    : {subject}")
    if scheduled:
        print(f"  Scheduled  : {scheduled}")
    print(f"  Priority   : {priority}")
    print()
    print("  Next step  :")
    print("    1. Open Pending_Approval/ and review the draft.")
    print("    2. Edit content if needed.")
    print(f"    3. Set  approved_by: human")
    print(f"         and  status: approved")
    print("    4. Move file to Approved/")
    print("    5. Orchestrator will pick it up automatically,")
    print("       or run: python watcher/social_media_executor_v2.py --execute \"<file>\"")
    print("=" * 62)
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="trigger_posts.py",
        description=(
            "Social Manager — draft generator.\n"
            "Saves a .md draft to Pending_Approval/ for human review before posting."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
PLATFORM EXAMPLES
-----------------

LinkedIn (professional post):
  python trigger_posts.py --platform linkedin \\
      --content "Excited to share that our team has just hit a major milestone..."

Twitter/X (short post, auto-truncate if needed):
  python trigger_posts.py --platform twitter \\
      --content "Big news dropping this Friday. Stay tuned! #launch #product" \\
      --allow-truncate

Facebook (long-form post with priority):
  python trigger_posts.py --platform facebook \\
      --content "Join us this Friday for our live product demo at 3 PM EST!" \\
      --priority high \\
      --scheduled "2026-03-01 09:00"

Instagram (image required):
  python trigger_posts.py --platform instagram \\
      --content "Behind the scenes at the office today. Hard work pays off!" \\
      --image-path "assets/bts-photo.jpg"

WhatsApp (recipient required):
  python trigger_posts.py --platform whatsapp \\
      --content "Hi! Reminder about our meeting tomorrow at 10 AM." \\
      --recipient "+447700900123"

Gmail (recipient + subject required):
  python trigger_posts.py --platform gmail \\
      --content "Hi team, please find this week's update attached." \\
      --recipient "team@company.com" \\
      --subject "Weekly Update — 27 Feb 2026"

Dry-run (preview, no file written):
  python trigger_posts.py --dry-run \\
      --platform linkedin \\
      --content "Testing my draft before committing."
        """,
    )

    parser.add_argument(
        "--platform", required=True,
        metavar="PLATFORM",
        help="facebook | instagram | linkedin | twitter | whatsapp | gmail",
    )
    parser.add_argument(
        "--content", required=True,
        metavar="TEXT",
        help="Post or message content (required)",
    )
    parser.add_argument(
        "--recipient", default="",
        metavar="CONTACT",
        help="Phone number or email address (required for whatsapp and gmail)",
    )
    parser.add_argument(
        "--subject", default="",
        metavar="SUBJECT",
        help="Email subject line (required for gmail)",
    )
    parser.add_argument(
        "--image-path", default="", dest="image_path",
        metavar="PATH",
        help="Image file path (required for instagram, optional for facebook)",
    )
    parser.add_argument(
        "--title", default="",
        metavar="TITLE",
        help="Post title (auto-generated from content if omitted)",
    )
    parser.add_argument(
        "--priority", default="medium",
        choices=["low", "medium", "high", "critical"],
        help="Orchestrator processing priority (default: medium)",
    )
    parser.add_argument(
        "--scheduled", default="",
        metavar="YYYY-MM-DD HH:MM",
        help="Schedule the post for a future date/time (executor respects this)",
    )
    parser.add_argument(
        "--allow-truncate", action="store_true", dest="allow_truncate",
        help="Twitter only: automatically truncate content to 280 chars",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Preview draft content without writing any file",
    )

    args = parser.parse_args()

    create_draft(
        platform      = args.platform,
        content       = args.content,
        recipient     = args.recipient,
        subject       = args.subject,
        image_path    = args.image_path,
        title         = args.title,
        priority      = args.priority,
        scheduled     = args.scheduled,
        allow_truncate= args.allow_truncate,
        dry_run       = args.dry_run,
    )


if __name__ == "__main__":
    main()
