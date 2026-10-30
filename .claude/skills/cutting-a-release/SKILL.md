---
name: cutting-a-release
description: Version and publish a release. Use when choosing a version number, deciding between MAJOR, MINOR and PATCH, naming a prerelease, writing release notes, or tagging a release.
---

# Cutting a Release

Creating a tag, merging or publishing needs explicit user approval every time
(`.claude/rules/git-workflow.md`). This skill says how, once approved.

## The version

Semantic Versioning, tagged `vMAJOR.MINOR.PATCH` on `main`; a prerelease reads `v2.0.0-rc.1`.

## Before tagging

1. The gates pass on the commit to tag. With a `.fullstack/catalog.yaml`,
   `node scripts/verify.mjs --out .orchestrate/release` exits 0 (run it in the background: it can
   outlive a foreground timeout). Without one, the repository's own test suites pass.
2. Release notes summarize user-visible changes and call out any breaking behaviour.
3. The user has explicitly approved the tag.

Only then create the tag.
