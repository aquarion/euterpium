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

1. Identify the current release tag and the previous release tag.
2. Fetch all pull requests merged between the previous release and the current release (by merge date or commit range).
3. Read each PR's title and body to understand what changed.
4. Write a concise "Release Highlights" section and **prepend** it to the current release's body using the `update_release` safe output.

## Output Format

Use this structure — omit any section that has no relevant entries:

```
## What's New

- **Feature name**: Brief description of user-visible benefit. (#PR)

## Bug Fixes

- Brief description of the fix and what it resolves. (#PR)

## Internal / Maintenance

- Brief description. (#PR)
```

Guidelines:
- Keep descriptions short and focused on user impact
- Group related PRs if they're part of the same feature
- Skip merge commits, dependency bumps, and version-bump-only PRs unless noteworthy
- Use plain language — no marketing fluff
- Do not include a summary paragraph before the sections; go straight to the headings

Use the `update_release` safe output with `operation: prepend` to add the highlights before the existing auto-generated notes.
