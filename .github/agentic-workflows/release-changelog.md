---
name: Release Changelog
description: Generate structured release highlights for a published Euterpium release using merged PRs and commits since the previous release.
on:
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      tag:
        description: "Release tag to generate highlights for (e.g. v2.3.0)"
        required: true
engine: copilot
timeout-minutes: 10
permissions:
  contents: read
  pull-requests: read
tools:
  github:
    toolsets:
      - pull_requests
      - repos
safe-outputs:
  update-release:
    max: 1
---

# Release Changelog Generator

You are generating structured release highlights for Euterpium, a Windows desktop app that identifies music playing in games using audio fingerprinting.

## Context

Euterpium is a small Python/tkinter app with:
- A system tray icon (pystray)
- Audio fingerprinting to identify music
- A Playnite plugin integration (C# .NET)
- An installer built with Inno Setup

The project uses conventional commit prefixes (`feat:`, `fix:`, `chore:`, etc.) but not strictly — use PR titles and descriptions as the primary source of truth.

## Your Task

1. Determine the current release tag:
   - If triggered by `workflow_dispatch`, use the provided `tag` input.
   - If triggered by the `release` event, use the tag from the triggering release.
2. Identify the previous release tag.
3. Fetch all pull requests merged between the previous release and the current release (by merge date or commit range).
4. Read each PR's title and body to understand what changed.
5. Write a concise "Release Highlights" section and update the current release's body using the `update_release` safe output.

**Idempotency:** Before writing, check whether the release body already contains the marker `<!-- gh-aw-release-highlights -->`. If it does, replace the existing block between `<!-- gh-aw-release-highlights -->` and `<!-- /gh-aw-release-highlights -->` with the new content (use `operation: replace` on the full body). If the marker is absent, prepend the new block (use `operation: prepend`).

## Output Format

Wrap the output in idempotency markers and omit any section that has no relevant entries:

```
<!-- gh-aw-release-highlights -->
## What's New

- **Feature name**: Brief description of user-visible benefit. (#PR)

## Bug Fixes

- Brief description of the fix and what it resolves. (#PR)

## Internal / Maintenance

- Brief description. (#PR)
<!-- /gh-aw-release-highlights -->
```

Guidelines:
- Keep descriptions short and focused on user impact
- Group related PRs if they're part of the same feature
- Skip merge commits, dependency bumps, and version-bump-only PRs unless noteworthy
- Use plain language — no marketing fluff
- Do not include a summary paragraph before the sections; go straight to the headings

Use the `update_release` safe output as described in step 5 above.
