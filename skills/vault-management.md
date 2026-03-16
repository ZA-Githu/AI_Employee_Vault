---
title: "Skill: Vault Management"
id: skill-vault-management
version: 1.0.0
tier: Bronze
tags: [skill, vault, dashboard]
---

# Skill: Vault Management
**ID:** skill-vault-management
**Version:** 1.0.0
**Tier:** Bronze
**Trigger:** Manual — user says "read file", "list files", "write file", or "update dashboard"

## Description

Handles all direct vault operations: reading files, writing files, listing folder contents, and updating the Dashboard.md with current status. This is the core file-system skill that all other skills depend on. It gives the agent controlled, auditable access to vault contents.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Read File | `read <filepath>` | Read and return the contents of any vault file |
| Write File | `write <filepath>` | Write or overwrite a file with given content |
| List Files | `list <folder>` | List all files in a given folder |
| Update Dashboard | `update dashboard` | Refresh counts and status in Dashboard.md |

## Inputs

- `operation` (string, required): One of `read | write | list | update-dashboard`
- `target_path` (string, required for read/write/list): Relative path inside the vault
- `content` (string, required for write): The content to write to the file
- `section` (string, optional, for update-dashboard): Specific Dashboard section to update

## Outputs

- **read:** Returns full file content as text
- **write:** Confirms file written, returns file path
- **list:** Returns a sorted list of filenames in the target folder
- **update-dashboard:** Returns confirmation with updated field values

## Steps

### Read File
1. Validate `target_path` exists inside the vault.
2. Read and return the full file content.
3. Log action type `READ`.

### Write File
1. Validate `target_path` is within an approved vault folder.
2. Write `content` to the file (create if missing, overwrite if exists).
3. Log action type `WRITE` or `CREATE`.

### List Files
1. Validate `target_path` is a valid vault folder.
2. List all `.md` files in that folder (non-recursive by default).
3. Return filenames as a numbered list.
4. Log action type `LIST`.

### Update Dashboard
1. Read `Dashboard.md`.
2. Count `.md` files in each of: `Inbox/`, `Needs_Action/`, `Done/`, `Logs/`.
3. Update the **Folder Counts** table with current numbers.
4. Update the **System Status** `Last Checked` column with today's date.
5. Write updated content back to `Dashboard.md`.
6. Log action type `EDIT`.

## Acceptance Criteria

- [ ] Read returns correct file content without modifying the file
- [ ] Write creates the file if it does not exist
- [ ] Write overwrites only if the user explicitly confirms for existing files
- [ ] List returns only files inside the specified folder
- [ ] Update Dashboard reflects accurate, current counts
- [ ] Every operation produces a log entry

## Constraints

- MUST NOT read or write outside the vault root directory
- MUST NOT write to `Logs/` directly — use the log-action skill
- MUST NOT delete files — deletion is a separate explicit action
- MUST NOT write to `Done/` notes that already exist there
- List operation is non-recursive unless explicitly requested

## Log Requirement

```
- `HH:MM:SS` | **<ACTION_TYPE>** | `<target_path>` | ✅ success / ❌ failed | <notes>
```
