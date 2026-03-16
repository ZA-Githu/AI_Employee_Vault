---
title: "Skill: LinkedIn Poster"
id: skill-linkedin-poster
version: 1.0.0
tier: Silver
tags: [skill, linkedin, social, posting, silver]
---

# Skill: LinkedIn Poster
**ID:** skill-linkedin-poster
**Version:** 1.0.0
**Tier:** Silver
**Trigger:** Manual — user says "post to linkedin <filename>" or "publish linkedin post <filename>"

## Description

Publishes an approved LinkedIn post to Ismat Zehra's LinkedIn profile. The post must already exist in `Approved/` with `approved_by: human` before this skill runs — it will not draft, not self-approve, and not publish anything that has not cleared the approval gate. After posting, it logs the outcome and moves the plan to `Done/`.

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Publish approved post | `post to linkedin <filename>` | Publish a post from Approved/ to LinkedIn |
| Preview post | `preview linkedin post <filename>` | Show the post content without publishing |
| Check post status | `linkedin post status <filename>` | Check if a post was successfully published |
| Schedule post | `schedule linkedin post <filename> <datetime>` | Queue post for a future time |
| List approved posts | `list linkedin posts` | Show all approved LinkedIn posts ready to publish |

## Inputs

- `filename` (string, required): Name of the approved plan file in `Approved/`
- `schedule_time` (string, optional): ISO datetime for scheduled posting (e.g. `2026-02-25T09:00:00`)
- `dry_run` (boolean, optional, default false): Preview post content without publishing

## Outputs

- Post published to LinkedIn (or scheduled)
- Plan frontmatter updated with `published: YYYY-MM-DD`, `post_url:`, `status: published`
- Plan moved to `Done/YYYY-MM/`
- One log entry with action type `SKILL_RUN` and post URL

## Steps

1. **Read constitutions.** Confirm Silver tier is active and LinkedIn policy (Section 7 of Company_Handbook.md) applies.
2. **Validate source.** Confirm `Approved/<filename>.md` exists. If not, log `ERROR` and abort.
3. **Check approval gate:**
   - `status` must be `approved`
   - `approved_by:` must be non-empty
   - `type` must be `linkedin-post`
   - If any check fails: log `ERROR`, inform human, abort
4. **Read post content** from the plan body (content between `## Proposed Actions` and the next section).
5. **Check credentials.** Verify LinkedIn API token is configured. If not, alert human and abort.
6. **Dry-run mode:** If enabled, print the post content and stop — do not publish.
7. **Publish or schedule:**
   - If no `schedule_time`: publish immediately via LinkedIn API
   - If `schedule_time` provided: schedule via LinkedIn API
8. **On success:**
   - Record `post_url` returned by LinkedIn API
   - Update plan frontmatter: `status: published`, `published: YYYY-MM-DD`, `post_url: <url>`
   - Move plan to `Done/YYYY-MM/<filename>.md`
   - Log `SKILL_RUN` with post URL
9. **On failure:**
   - Log `ERROR` with API response
   - Leave plan in `Approved/` — do not move to Done
   - Alert human with failure reason

## Acceptance Criteria

- [ ] Post is only published if `Approved/<filename>.md` exists with `approved_by:` set
- [ ] Agent refuses to publish if plan type is not `linkedin-post`
- [ ] Dry-run mode shows content without publishing
- [ ] Published plan is moved to `Done/YYYY-MM/` after successful posting
- [ ] `post_url` is recorded in the plan's frontmatter
- [ ] Log entry includes action type `SKILL_RUN` and post URL
- [ ] Failed posts are logged and left in `Approved/` for retry

## Constraints

- MUST NOT publish any post not in `Approved/` with `approved_by: human`
- MUST NOT edit post content — publish exactly what was approved
- MUST NOT publish more than 3 posts per day (LinkedIn rate limit policy)
- MUST NOT publish to a personal profile without valid OAuth credentials
- MUST NOT delete or edit a published LinkedIn post without explicit human instruction
- MUST abort if `type: linkedin-post` is not set on the plan

## Error Cases

| Error | Response |
|-------|----------|
| File not in Approved/ | Log ERROR, abort, tell human the correct workflow |
| Missing `approved_by:` | Log ERROR, refuse to publish |
| LinkedIn API auth failure | Alert human to re-authenticate, leave plan in Approved/ |
| LinkedIn API rate limit | Log WARNING, inform human, suggest retry time |
| Post content too long (>3000 chars) | Alert human — LinkedIn limit exceeded, needs editing |
| Network failure | Retry once after 10 seconds; if fails, log ERROR |

## Log Requirement

**On successful publish:**
```
- `HH:MM:SS` | **SKILL_RUN** | `Approved/<filename>.md` → `Done/YYYY-MM/<filename>.md` | ✅ success | linkedin post published: <post_url>
```
**On failure:**
```
- `HH:MM:SS` | **SKILL_RUN** | `Approved/<filename>.md` | ❌ failed | linkedin publish error: <reason>
```
