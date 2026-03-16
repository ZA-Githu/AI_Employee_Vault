---
title: "Social Media Manager Constitution"
type: constitution
tier: Gold — Social Manager Extension
version: 1.0
created: 2026-02-27
author: Ismat Zehra
status: active
tags: [constitution, social-manager, gold, hitl]
---

# Social Media Manager Constitution
## Semi-Autonomous AI Social Media Manager

> Built on top of the AI_Employee_Vault Gold Tier.
> Owner: Ismat Zehra | Agent: Claude | Architecture: Python + Playwright + HITL

---

## 1. Purpose

This constitution governs the Semi-Autonomous AI Social Media Manager — a
Human-in-the-Loop (HITL) system that drafts, queues, approves, and publishes
content across WhatsApp, Facebook, LinkedIn, Twitter/X, Instagram, and Gmail
using persistent browser sessions managed by Playwright.

The system extends the existing Gold Tier vault without replacing it.
All existing approval pipelines, audit logs, and Ralph Loop plans remain
fully operational.

---

## 2. Guiding Principles

1. **Never post without human approval.** Every draft must pass through
   `Pending_Approval/` and be explicitly moved to `Approved/` by a human
   before any script touches a platform.

2. **Login once, never again.** Each platform session is saved permanently to
   `session/<platform>/`. Once authenticated, no script ever opens a login
   page again unless the session expires.

3. **Fail loudly, recover gracefully.** On any failure, a screenshot is saved
   to `Logs/screenshots/` and a structured error entry is appended to
   `Logs/YYYY-MM-DD.json`. The failed post stays in `Approved/` for retry —
   it is never silently dropped.

4. **Terminal-first operation.** All triggering, approval, and monitoring is
   done from the terminal. No GUI required beyond the browser Playwright opens.

5. **One file, one post.** Each Markdown file in `Pending_Approval/` or
   `Approved/` represents exactly one post on exactly one platform. No batch
   files, no multi-platform single-file shortcuts.

6. **Logs are append-only.** No log entry is ever deleted or modified. Every
   action (draft created, post approved, post published, failure, screenshot)
   produces a structured JSON + Markdown log line.

---

## 3. Folder Structure

```
AI_Employee_Vault/
├── Pending_Approval/          ← Drafts waiting for human review
│   └── YYYY-MM-DD — Title — platform.md
├── Approved/                  ← Human-approved posts ready to publish
│   └── YYYY-MM-DD — Title — platform.md
├── Done/                      ← Successfully published posts (archived)
│   └── YYYY-MM/
│       └── YYYY-MM-DD — Title — platform.md
├── session/                   ← Persistent Playwright browser sessions
│   ├── facebook/              ← Chromium profile for Facebook
│   ├── instagram/             ← Chromium profile for Instagram
│   ├── linkedin/              ← Chromium profile for LinkedIn
│   ├── twitter/               ← Chromium profile for Twitter/X
│   ├── whatsapp/              ← Chromium profile for WhatsApp Web
│   └── gmail/                 ← Chromium profile for Gmail
├── Logs/                      ← All logs (JSON + MD + screenshots)
│   ├── YYYY-MM-DD.json        ← Machine-readable structured log
│   ├── YYYY-MM-DD.md          ← Human-readable Markdown log
│   └── screenshots/           ← Failure screenshots (PNG, named by timestamp)
└── watcher/                   ← All Python scripts (unchanged Gold Tier location)
    ├── social_media_executor_v2.py   ← Posts content via Playwright
    ├── master_orchestrator.py        ← Monitors Approved/ and triggers executor
    └── trigger_posts.py              ← Generates post drafts → Pending_Approval/
```

---

## 4. Post File Format

Every post file must have valid YAML frontmatter. The executor reads these
fields and rejects any file missing required fields.

```markdown
---
title: "My Post Title"
platform: facebook            # facebook | instagram | linkedin | twitter | whatsapp | gmail
type: social-post             # always "social-post" for executor
status: pending               # pending | approved | published | failed
approved_by: human            # REQUIRED before executor will act — must not be blank
created: 2026-02-27
scheduled: 2026-02-27 10:00   # optional — executor checks this before posting
priority: medium              # low | medium | high | critical
allow_truncate: false         # twitter only — truncate to 280 chars if true
image_path:                   # instagram/facebook only — full local path to image
recipient:                    # whatsapp/gmail only — phone number or email address
subject:                      # gmail only — email subject line
tags: [social, draft]
---

## Post Content

Your post text goes here.

For Twitter: keep under 280 characters.
For Instagram: caption goes here; set image_path in frontmatter.
For WhatsApp: the recipient field above is the phone number or contact name.
For Gmail: subject is the email subject, recipient is the To: address.
```

### Required fields by platform

| Field | Facebook | Instagram | LinkedIn | Twitter | WhatsApp | Gmail |
|-------|----------|-----------|----------|---------|----------|-------|
| `platform` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `approved_by` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `image_path` | optional | ✅ required | ❌ | ❌ | ❌ | ❌ |
| `recipient` | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| `subject` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `allow_truncate` | ❌ | ❌ | ❌ | optional | ❌ | ❌ |

---

## 5. The Three Scripts

### 5.1 trigger_posts.py — Draft Generator

**Purpose:** Generates post draft files in `Pending_Approval/` from the terminal.

**Run from terminal:**
```bash
cd watcher

# Create a Facebook post draft
python trigger_posts.py --platform facebook --title "My Post" --content "Post text here"

# Create from a content file
python trigger_posts.py --platform twitter --file content.md

# Interactive mode (prompts for all fields)
python trigger_posts.py --interactive

# Batch: generate drafts for all platforms from one content block
python trigger_posts.py --all-platforms --title "Launch Announcement"
```

**What it does:**
1. Accepts platform, title, and content via CLI args or interactive prompts
2. Validates platform-specific requirements (e.g. Twitter ≤280 chars)
3. Writes a properly-formatted `.md` file to `Pending_Approval/`
4. Logs the draft creation to `Logs/YYYY-MM-DD.json`
5. Prints the filename so the human knows what to review

**Output:** `Pending_Approval/YYYY-MM-DD — My Post — facebook.md`

---

### 5.2 social_media_executor_v2.py — Platform Poster

**Purpose:** Given an approved post file, opens the platform in Playwright
(using the saved persistent session) and publishes the post.

**Run from terminal:**
```bash
cd watcher

# Post one specific approved file
python social_media_executor_v2.py --post "2026-02-27 — My Post — facebook.md"

# Dry-run (validate file, no browser)
python social_media_executor_v2.py --post "2026-02-27 — My Post — facebook.md" --dry-run

# Post all approved files for one platform
python social_media_executor_v2.py --platform facebook

# Post all approved files across all platforms
python social_media_executor_v2.py --all
```

**What it does:**
1. Reads the approved file from `Approved/`
2. Validates `approved_by` is set — **hard stop if missing**
3. Launches Playwright with the saved session from `session/<platform>/`
4. If not logged in: opens browser for manual login, saves session, then posts
5. Publishes the post using platform-specific selectors
6. On success: moves file to `Done/YYYY-MM/`, logs `SOCIAL_POST` to JSON + MD
7. On failure: saves screenshot to `Logs/screenshots/YYYY-MM-DD-HH-MM-<platform>.png`,
   logs error to JSON + MD, leaves file in `Approved/` for retry

**Platforms supported:**
- `facebook` — posts to feed via facebook.com
- `instagram` — posts with image upload via instagram.com
- `linkedin` — posts to feed via linkedin.com
- `twitter` — posts tweet via x.com (max 280 chars)
- `whatsapp` — sends message to contact via web.whatsapp.com
- `gmail` — sends email via gmail.com compose

---

### 5.3 master_orchestrator.py — Continuous Monitor

**Purpose:** Watches `Approved/` for new files and automatically calls the
executor. Runs continuously in the background (or via PM2).

**Run from terminal:**
```bash
cd watcher

# Start continuous monitoring
python master_orchestrator.py

# Monitor with 60-second poll interval
python master_orchestrator.py --interval 60

# One-shot: process everything in Approved/ right now, then exit
python master_orchestrator.py --once

# Dry-run: show what would be posted, no browser
python master_orchestrator.py --dry-run
```

**What it does:**
1. Polls `Approved/` every N seconds (default: 60)
2. For each `.md` file found with `approved_by` set and `status: approved`:
   - Calls `social_media_executor_v2.py` for that file
   - Waits for completion before picking up the next file
3. Logs every poll cycle to `Logs/YYYY-MM-DD.json`
4. On executor failure: logs screenshot path, marks file with `status: failed`,
   leaves it in `Approved/` — does NOT retry automatically (human must re-approve)
5. Sends a summary to `Logs/` after each successful or failed post

**Stop the monitor:** Ctrl+C for clean shutdown.

---

## 6. Session Management — Login Once

Each platform has a dedicated Playwright persistent context directory under
`session/<platform>/`. The first time a script runs for a platform, it opens
a visible browser window and waits for the human to log in manually. After
login, the session (cookies, localStorage) is saved automatically.

**Subsequent runs:** the browser opens directly to the platform's home page
already logged in — no manual action required.

**Session directories:**
```
session/
  facebook/    → session for Facebook poster
  instagram/   → session for Instagram poster
  linkedin/    → session for LinkedIn poster
  twitter/     → session for Twitter/X poster
  whatsapp/    → session for WhatsApp Web
  gmail/       → session for Gmail sender
```

**Session expiry:** If a session expires (platform logged out), the executor
detects the login page, logs an L3 escalation to `Needs_Action/`, and stops
that platform's processing. Other platforms continue unaffected. The human
re-authenticates by running the executor once manually for that platform.

---

## 7. Robustness Rules

### 7.1 Screenshots on failure
Every Playwright failure (selector not found, timeout, network error) triggers:
```
Logs/screenshots/YYYY-MM-DD-HH-MM-SS-<platform>-<post-slug>.png
```
The screenshot path is recorded in the JSON log entry under `"screenshot"`.

### 7.2 Retry policy
- Executor does **not** auto-retry failed posts
- Failed posts stay in `Approved/` with `status: failed` in frontmatter
- The human re-queues by resetting `status: approved` in the file
- This prevents double-posting on platforms

### 7.3 Approved/ is the source of truth
- A post in `Approved/` with `approved_by` set = ready to post
- A post in `Approved/` with `status: failed` = needs human attention
- A post in `Done/` = successfully published (do not re-process)
- A post in `Pending_Approval/` = not yet approved (executor ignores it)

### 7.4 Executor never touches Pending_Approval/
The executor only reads from `Approved/`. It never reads, modifies, or moves
files in `Pending_Approval/`. Only humans (or trigger_posts.py on draft
creation) interact with `Pending_Approval/`.

### 7.5 Platform character limits enforced before browser opens
| Platform | Limit | Behavior if exceeded |
|----------|-------|---------------------|
| Twitter/X | 280 chars | Rejected unless `allow_truncate: true` |
| Instagram caption | 2,200 chars | Hard reject |
| Facebook post | 63,206 chars | Hard reject |
| LinkedIn post | 3,000 chars | Hard reject |
| WhatsApp message | 65,536 chars | Hard reject |
| Gmail body | no hard limit | Warn if >10,000 chars |

---

## 8. Logging Format

### JSON log entry (Logs/YYYY-MM-DD.json)
```json
{
  "timestamp": "2026-02-27T10:15:33",
  "action_type": "SOCIAL_POST",
  "skill": "social-media-executor-v2",
  "platform": "facebook",
  "source": "Approved/2026-02-27 — My Post — facebook.md",
  "destination": "Done/2026-02/2026-02-27 — My Post — facebook.md",
  "outcome": "success",
  "post_url": "https://facebook.com/posts/123456",
  "screenshot": null,
  "notes": "platform: facebook | chars: 240",
  "tier": "gold"
}
```

### On failure:
```json
{
  "timestamp": "2026-02-27T10:16:01",
  "action_type": "SOCIAL_POST",
  "skill": "social-media-executor-v2",
  "platform": "instagram",
  "source": "Approved/2026-02-27 — My Post — instagram.md",
  "destination": null,
  "outcome": "failed",
  "post_url": null,
  "screenshot": "Logs/screenshots/2026-02-27-10-16-01-instagram-my-post.png",
  "notes": "TimeoutError: could not find Share button",
  "tier": "gold"
}
```

---

## 9. Full Workflow — Step by Step

```
STEP 1 — DRAFT
  Human tells Claude: "draft a linkedin post about our product launch"
  OR: python watcher/trigger_posts.py --platform linkedin --interactive
  → File created: Pending_Approval/2026-02-27 — Product Launch — linkedin.md

STEP 2 — REVIEW
  Human opens Pending_Approval/ in Obsidian or any text editor
  Human edits the post content if needed
  Human adds to frontmatter:
      approved_by: human
      status: approved
  Human moves file to Approved/
  (OR: human tells Claude "approve plan [filename]" which does this automatically)

STEP 3 — EXECUTE (two options)
  Option A — Manual one-shot:
      python watcher/social_media_executor_v2.py --post "filename.md"

  Option B — Automatic via orchestrator:
      python watcher/master_orchestrator.py    (runs continuously)
      → detects new file in Approved/ → calls executor automatically

STEP 4 — RESULT
  Success → file moved to Done/YYYY-MM/, log entry written, post URL recorded
  Failure → screenshot saved, log entry written, file stays in Approved/

STEP 5 — VERIFY
  Open Logs/YYYY-MM-DD.json to see the full structured log
  Open Logs/YYYY-MM-DD.md for human-readable summary
  Check Done/ to confirm the post was archived
```

---

## 10. PM2 Integration

The orchestrator can run persistently under PM2 alongside existing Gold Tier watchers:

```bash
# Add to ecosystem.config.js:
{
  name: "social-orchestrator",
  script: "master_orchestrator.py",
  interpreter: "python",
  cwd: "C:\\Users\\Ismat Zehra\\3D Objects\\hackathon0\\AI_Employee_Vault\\watcher",
  args: "--interval 60",
  autorestart: true,
  max_restarts: 10,
  restart_delay: 15000,
  out_file: "..\\Logs\\pm2-social-orchestrator-out.log",
  error_file: "..\\Logs\\pm2-social-orchestrator-err.log"
}
```

---

## 11. What This System Does NOT Do

- Does not post without `approved_by: human` — ever
- Does not auto-retry failed posts — human must re-approve
- Does not manage scheduling (posts execute as soon as approved, unless `scheduled:` is set)
- Does not generate content autonomously — Claude drafts, human approves
- Does not delete or overwrite existing posts on platforms
- Does not read or scrape platform feeds (read-only access via Gold Tier watchers)

---

## 12. Compatibility with Existing Gold Tier

| Existing component | Impact |
|-------------------|--------|
| `Pending_Approval/` | Shared — social manager adds files here |
| `Approved/` | Shared — social manager reads `type: social-post` files only |
| `Done/` | Shared — social manager archives to `Done/YYYY-MM/` |
| `Logs/` | Shared — appends to same JSON + MD daily logs |
| `audit_logger.py` | Used by executor and orchestrator |
| `watcher/sessions/` | Gold Tier sessions — untouched |
| `session/` | NEW — social manager sessions (separate from watcher/sessions/) |
| `facebook_poster.py` etc. | Gold Tier posters — still operational, independent |

The social manager scripts (`social_media_executor_v2.py`, `master_orchestrator.py`,
`trigger_posts.py`) are **additive** — they do not replace or modify any existing
Gold Tier script.

---

*Social-Manager-Constitution.md | AI_Employee_Vault Gold Tier Extension | Hackathon 2026*
