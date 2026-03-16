---
title: "Skill: Social Poster"
id: skill-social-poster
version: 2.0.0
tier: Gold
tags: [skill, social, facebook, instagram, twitter, linkedin, watcher, gold]
---

# Skill: Social Poster
**ID:** skill-social-poster
**Version:** 2.0.0
**Tier:** Gold
**Trigger:**
- Post: `post to <platform> <filename>` | `publish <platform> post <filename>`
- Watch: `watch <platform>` | auto-on at PM2 startup
- Summary: `weekly social summary` | auto-on Sunday

## Description

Gold Tier social skill covering **posting** and **watching** across Facebook, Instagram, Twitter/X, and LinkedIn. Enforces human-in-the-loop approval for all outbound posts via `Pending_Approval/` → `Approved/` workflow. Watches incoming social activity (mentions, DMs, comments) and routes items to `Needs_Action/` or `Inbox/` using keyword triggers. Generates a weekly `Social_Summaries/` report every Sunday.

LinkedIn posts use `skills/linkedin-poster.md`. This skill handles Facebook, Instagram, and Twitter/X — plus the unified weekly summary across all four platforms.

---

## Capabilities

| Capability | Command | Description |
|-----------|---------|-------------|
| Post to Facebook | `post to facebook <filename>` | Publish approved plan to Facebook |
| Post to Instagram | `post to instagram <filename>` | Publish approved plan to Instagram |
| Post to Twitter/X | `post to twitter <filename>` | Publish approved tweet to Twitter/X |
| Watch Facebook | `watch facebook` | Monitor messages, mentions, notifications |
| Watch Instagram | `watch instagram` | Monitor DMs, mentions, comments |
| Watch Twitter | `watch twitter` | Monitor mentions, DMs, replies |
| Weekly Summary | `weekly social summary` | Summarise all platforms activity for the week |
| List pending | `list social posts` | Show all approved posts ready to publish |

---

## Platform Rules

| Platform | Type Field | Char Limit | Session Dir | Watch Targets |
|----------|-----------|-----------|-------------|--------------|
| Facebook | `facebook-post` | 63,206 | `watcher/sessions/facebook/` | Messages, Mentions, Notifications |
| Instagram | `instagram-post` | 2,200 | `watcher/sessions/instagram/` | DMs, Mentions, Comments |
| Twitter/X | `twitter-post` | 280 | `watcher/sessions/twitter/` | Mentions, DMs, Replies |
| LinkedIn | `linkedin-post` | 3,000 | `watcher/sessions/linkedin/` | *(handled by linkedin-poster.md)* |

---

## Inputs

### Posting Mode
- `platform` (string, required): `facebook` | `instagram` | `twitter`
- `filename` (string, required): Approved plan filename in `Approved/`
- `dry_run` (boolean, optional): Preview post, no browser action

### Watch Mode
- `platform` (string, required): Platform to watch
- `interval` (integer, optional): Poll interval in seconds (default: 300)
- `once` (boolean, optional): Single pass then exit

### Summary Mode
- `week` (string, optional): ISO week `YYYY-WW` (defaults to current week)

---

## Outputs

### Posting Mode
- Post published on target platform
- Plan frontmatter: `status: published`, `published: YYYY-MM-DD`, `post_url: <url>`
- Plan moved from `Approved/` → `Done/YYYY-MM/`
- `Social_Summaries/YYYY-WW — Social-Summary.md` updated
- Log entry: `SOCIAL_POST`

### Watch Mode
- New `Needs_Action/` note for keyword-matched items
- New `Inbox/` note for general activity
- Log entries: `CREATE` for each routed item

### Summary Mode
- `Social_Summaries/YYYY-WW — Social-Summary.md` written/updated
- `Dashboard.md` updated with summary link
- Log entry: `SOCIAL_SUMMARY`

---

## Approval Gate (Mandatory — Cannot Be Bypassed)

Before any post is published, ALL of these must be true:

```yaml
# The plan file in Approved/ must have:
status: approved
approved_by: human          # must be non-empty
type: facebook-post         # OR instagram-post OR twitter-post
published: ~                # must NOT already be set
```

If any condition fails → log `ERROR` → abort → tell human → do NOT publish.

---

## Steps — Posting Mode

1. **Confirm constitutions.** Gold tier active. Approval gate in force.
2. **Locate file.** Confirm `Approved/<filename>.md` exists. If not → `ERROR` + abort.
3. **Validate approval gate.** Check all 4 conditions above. Any failure → abort.
4. **Read post content.** Extract from `## Post Content` or `## Proposed Actions` section.
5. **Check char limit.** If over platform limit → `ERROR` + abort (never silently truncate).
6. **Dry-run check.** If `dry_run: true` → print content and stop. Log `SKILL_RUN` dry-run.
7. **Launch browser.** Open Playwright with `watcher/sessions/<platform>/` profile.
8. **Check login.** If not logged in, wait 60s for manual login. Timeout → `ERROR` + abort.
9. **Navigate and post.** Automate the post creation flow on the platform.
10. **On success:** Record `post_url`. Update plan frontmatter. Move plan to `Done/YYYY-MM/`. Update `Social_Summaries/`. Log `SOCIAL_POST`.
11. **On failure:** Log `ERROR`. Leave plan in `Approved/` for retry. Call `skills/error-recovery.md`.

---

## Steps — Watch Mode

1. **Launch browser** with platform session dir. Check login.
2. **Poll for new activity** every `interval` seconds:
   - Facebook: unread messages, page notifications, mentions
   - Instagram: unread DMs, comment mentions, tagged posts
   - Twitter/X: unread mentions, DMs, replies to recent tweets
3. **Classify each item** against `SOCIAL_KEYWORDS` env var (default: urgent, action, meeting, reply, question, complaint, review).
4. **Route:**
   - Keyword match → `Needs_Action/YYYY-MM-DD HH-MM — <platform>-<contact>.md`
   - No keyword match → `Inbox/YYYY-MM-DD HH-MM — <platform>-<contact>.md`
5. **Log** each routed item with action type `CREATE`.

---

## Steps — Weekly Summary Mode

1. Read all `SOCIAL_POST` log entries from `Logs/` for the current ISO week.
2. Count posts per platform. List post titles and publish dates.
3. Read `Needs_Action/` and `Inbox/` for items tagged `[facebook]`, `[instagram]`, `[twitter]`, `[linkedin]`.
4. Write/update `Social_Summaries/YYYY-WW — Social-Summary.md`.
5. Update `Dashboard.md` under `## Social Activity`.
6. Log `SOCIAL_SUMMARY`.

---

## Example Frontmatter — Approved Post

```yaml
---
title: "Product Launch Tweet"
type: twitter-post
status: approved
approved_by: human
approved_date: 2026-02-25
priority: high
author: claude
tags: [twitter, social, product]
---

## Post Content

Exciting news! Our new feature is live. Try it today and let us know what you think. #product #launch
```

---

## Acceptance Criteria

- [ ] No post published without `Approved/` entry with `approved_by: human`
- [ ] Char limit enforced per platform — no silent truncation
- [ ] Dry-run mode works without browser
- [ ] Published plan moved to `Done/YYYY-MM/` with `post_url` recorded
- [ ] Watch mode routes keyword items to `Needs_Action/`, rest to `Inbox/`
- [ ] Weekly summary written to `Social_Summaries/` and linked on `Dashboard.md`
- [ ] All actions logged with correct action type

## Constraints

- MUST NOT publish without `approved_by: human` in frontmatter
- MUST NOT modify post content after approval — publish exactly as written
- MUST NOT publish > 5 posts/day per platform
- MUST NOT share session dirs between platforms
- MUST abort if char limit exceeded (never truncate)
- MUST call `skills/error-recovery.md` on any browser failure

## Related Skills

- `skills/linkedin-poster.md` — LinkedIn posting (separate skill)
- `skills/weekly-audit.md` — consumes `Social_Summaries/` for CEO Briefing
- `skills/error-recovery.md` — called on failure
- `skills/ralph-wiggum.md` — may chain this skill in multi-step loops

## Log Requirement

```
- `HH:MM:SS` | **SOCIAL_POST** | `Approved/<file>.md` → `Done/YYYY-MM/<file>.md` | ✅ | platform: twitter | url: <url>
- `HH:MM:SS` | **CREATE** | `twitter:mention` → `Needs_Action/2026-02-25 14-30 — twitter-mention.md` | ✅ | keywords: true
- `HH:MM:SS` | **SOCIAL_SUMMARY** | `Logs/` → `Social_Summaries/2026-09.md` | ✅ | posts: 7 | platforms: 4
```
