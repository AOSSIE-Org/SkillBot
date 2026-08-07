# Brand Guidelines

This document outlines the brand guidelines, visual identity, and communication tone for **Skill Bot**, the Discord assistant module of the **AOSSIE Skills Ecosystem**.


## Visual Identity

### Logos and Assets

All official logos are stored in the [`/public`](./public) directory of this repository.

- **Skills Ecosystem Logo:** `/public/skills-logo.svg` — The primary logo for the project. A dark folder glyph with blurred red and blue "context" blobs and an orange highlight card, capped with pixel-art `SKILLS.MD` text. Represents the ecosystem's core idea: project knowledge (skills) captured and organized as living documentation. Use this as Skill Bot's primary mark in README headers and cross-ecosystem materials.
- **AOSSIE Logo:** `/public/aossie-logo.svg` — Parent organization mark. Used alongside the Skills Ecosystem logo in README headers and cross-org materials, never as a substitute for it.
- **Stability Nexus Badge:** `/public/stability.svg` — Project stability status indicator, shown in README headers.

Use `skills-logo.svg` on dark or neutral backgrounds — its base fill (`#1C1818`) is designed to sit on dark surfaces; on light backgrounds, keep it inside a dark card/container rather than placing it directly on white.

### Color Palette

The palette is drawn directly from the Skills Ecosystem logo and is shared across every module in the ecosystem (Skills Core, PR Dashboard, Skill Bot, Skill Updater) so cross-linked docs, dashboards, and bot messages read as one system.

* **Folder Base (Dark Glass):** `#1C1818`
  * The logo's base fill. Use for dark surfaces and containers behind the logo.
* **Signal Red (Primary Accent):** `#A82020`
  * The dominant logo blob color. Use for error states, failed inference notices, and critical Discord embed alerts (e.g. "no matching skill found, escalated to maintainer").
* **Signal Blue (Secondary Accent):** `#0C66A6`
  * The cooler logo blob color. Use for informational embeds, links to other ecosystem modules, and neutral status messages.
* **Skills Orange (Highlight):** `#E37A4B`
  * Used for the logo's folder outline, the accent card, and the `SKILLS.MD` pixel text. This is the "call to action" color — use it for the most important highlight in a response (e.g. a suggested next step or a link to the relevant skill file).
* **Discord Embed Colors:** when composing `discord.py` embeds, map the intent of the message to the palette above rather than using Discord's default blurple:
  * Success / answer found → Signal Blue (`0x0C66A6`)
  * Escalation / gap logged → Skills Orange (`0xE37A4B`)
  * Error / repository not recognized → Signal Red (`0xA82020`)
* **Accessibility Target:** All text pairings must meet or exceed WCAG 2.1 AA (4.5:1) contrast. On the dark folder base (`#1C1818`), use near-white text (`#F8FAFC` or lighter) for body copy — do not rely on the accent blob colors alone for readable text.

## Typography

Skill Bot's primary surface is Discord, which renders its own client typography — this section governs only the repository's Markdown docs (README, roadmap) and any generated HTML/log summaries.

- **Primary Stack:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Monospace (filenames, repo names, commands):** always wrap `AGENTS.md`, `gap_log.json`, `repo_router.py`, and slash/CLI commands in inline code formatting.
- **Weights:** Regular (400) for body copy; Bold (700–800) for module names and headings.
- **Usage:** In Discord responses, use Markdown bold (`**text**`) for the key answer or recommendation, and inline code for file paths or commands — keep responses skimmable in a chat thread rather than dense paragraphs.

## Terminology & Copywriting

When writing documentation, bot responses, or community announcements, strictly adhere to the following:

- **Skill Bot** (two words, capitalized) — this project's name. Do not write "SkillBot" or "skill bot" in user-facing text (the one-word form is reserved for the GitHub repository name only).
- **AOSSIE Skills Ecosystem** — the overall project (not "skills ecosystem" or "Skills ecosystem" mid-sentence unless it's clearly a continuation).
- **Skills Core** — the organization-wide repository of shared skills and policies that Skill Bot queries ([AOSSIE-Org/Skills](https://github.com/AOSSIE-Org/Skills)).
- **PR Dashboard** — the merge-analysis module ([AOSSIE-Org/PullRequestDashboard](https://github.com/AOSSIE-Org/PullRequestDashboard)).
- **Skill Updater** (two words, capitalized) — the knowledge-evolution/PR pipeline module that consumes Skill Bot's gap logs.
- **`AGENTS.md`** — the per-repository agent-boundary and context file; always in inline code formatting, always capitalized exactly as shown.
- **Gap signal** / **`gap_log.json`** — the mechanism by which Skill Bot records unanswered or under-documented questions for the Skill Updater to pick up; always use "gap signal" (not "gap event" or "gap ticket") in prose, and inline-code the filename.
- **Local-first** (hyphenated, lowercase) — describes Skill Bot's core design principle (local Ollama inference, no external API calls); use consistently rather than "local first" or "Local First".
