---
title: "Skill: File Processing"
id: skill-file-processing
version: 1.0.0
tier: Bronze
tags: [skill, inbox, triage, processing]
---

# Skill: File Processing
**ID:** skill-file-processing
**Version:** 1.0.0
**Tier:** Bronze
**Trigger:** Manual — user says "process inbox", "triage inbox", or "process file <filename>"

## Description

Processes files dropped into the `Inbox/` folder. Reads each file, determines its type and intent, adds required frontmatter, and routes it to the correct destination folder (`Needs_Action/` or `Done/`). This is the primary intake skill — it transforms raw dropped files into properly structured vault notes.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Process All | `process inbox` | Process every file currently in Inbox/ |
| Process One | `process file <filename>` | Process a single named file from Inbox/ |
| Dry Run | `process inbox --dry-run` | Show what would happen without moving files |
| Show Queue | `inbox status` | List all files waiting in Inbox/ |

## Inputs

- `mode` (string, required): One of `all | single | dry-run | status`
- `filename` (string, required for single mode): Name of the file in Inbox/ to process
- `override_destination` (string, optional): Force destination to `Needs_Action` or `Done`

## Outputs

- Files moved from `Inbox/` to `Needs_Action/` or `Done/`
- Updated frontmatter on each processed file
- Processing summary returned to user
- One log entry per file processed

## Steps

1. **List Inbox.** Use vault-management skill to list all files in `Inbox/`.
2. **Check queue.** If Inbox is empty, report "Inbox is clear" and stop.
3. **For each file to process:**

   a. **Read the file** using vault-management skill.

   b. **Classify intent** by reading title and body:
      - Contains action words (do, write, send, fix, review, call, build) → `Needs_Action/`
      - Already resolved, informational, reference only → `Done/`
      - Noise, empty, or duplicate → flag for deletion (log reason)

   c. **Add required frontmatter** based on destination:

      For `Needs_Action/`:
      ```yaml
      ---
      title: "<derived from filename or first heading>"
      status: pending
      priority: medium
      created: YYYY-MM-DD
      due: YYYY-MM-DD
      tags: [action, agent]
      agent_assigned: claude
      ---
      ```

      For `Done/`:
      ```yaml
      ---
      title: "<derived from filename or first heading>"
      status: done
      created: YYYY-MM-DD
      completed: YYYY-MM-DD
      resolution: "Archived from Inbox — informational content"
      tags: [done, agent]
      ---
      ```

   d. **Move the file** to destination using vault-management skill.

   e. **Log the action** using action type `TRIAGE`.

4. **Handle deletions.** For noise/duplicate files: log `DELETE` with reason, then remove.
5. **Report summary.** Return: X moved to Needs_Action, Y moved to Done, Z deleted.

## Acceptance Criteria

- [ ] All Inbox files are processed — none left without a log entry
- [ ] Every moved file has complete, valid frontmatter for its destination
- [ ] No file body content is modified — only frontmatter added
- [ ] One log entry exists per processed file
- [ ] No silent deletions — all removals are logged with reason
- [ ] Processing summary is returned to the user
- [ ] Dry-run mode makes no changes to files

## Constraints

- MUST NOT modify the body content of any file — frontmatter only
- MUST NOT process files outside of `Inbox/`
- MUST NOT move files directly to `Logs/` or `.claude/`
- MUST NOT create new folders outside the approved structure
- MUST stop and report if a file cannot be read or parsed
- MUST ask for human confirmation before deleting any file

## Error Cases

| Error | Response |
|-------|----------|
| Inbox is empty | Report "Inbox is clear", stop gracefully |
| File has no readable content | Flag to human, skip and log `ERROR` |
| Cannot determine destination | Default to `Needs_Action/`, note uncertainty in log |
| Destination file already exists | Append timestamp suffix to filename to avoid overwrite |

## Log Requirement

One entry per file processed:
```
- `HH:MM:SS` | **TRIAGE** | `Inbox/<file>.md` → `<dest>/<file>.md` | ✅ success / ❌ failed | reason: <one sentence>
```
