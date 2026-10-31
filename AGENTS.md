# AGENTS.md — Skill Bot

Skill Bot is a local-first Discord assistant, and a template any organization can copy. It
watches a Discord channel, detects which repository (from `repo_metadata.py`) a contributor is
asking about, loads only the docs from that repository that match the question, and answers via
a local Ollama model. When no doc matches, it asks which project is meant or says the docs don't
cover it, and writes a `gap_log.json` entry.

## Setup & Run

```bash
python -m venv venv
source venv/bin/activate        # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # fill in DISCORD_TOKEN, DISCORD_CHANNEL_ID
ollama pull llama3.2            # or whatever OLLAMA_MODEL is set to
python bot.py
```

Requires Python 3.10+, a running local Ollama instance, and a Discord bot token with the
`Message Content` intent. On Windows, `start_bot_hidden.vbs` runs the bot
silently in the background instead of `python bot.py`.

## Code Map

- `bot.py` — Discord event loop: message handling, thread-per-query creation, Ollama calls,
  backlog recovery on startup (last `BACKLOG_MAX_AGE_HOURS` only), docs sync loop.
- `repo_router.py` — repository detection (longest keyword/name match → LLM classification
  fallback), per-question context loading, clarification requests, GitHub issue/comment helpers.
- `repo_metadata.py` — the repositories the bot answers about: URL, description, keywords and
  the `docs` paths to copy. A template: each organization replaces the example entry.
- `scripts/update_subtrees.py` — copies each entry's `docs` into `repos/<name>/`. The bot runs it
  at startup and every `SYNC_INTERVAL_HOURS`; it can also be run by hand to check the list.
- `.clinerules` — system prompt for the "Open Source Clarification & Guardrail Assistant"
  fallback persona, used when a query can't be routed to a specific repo.
- `repos/` — generated, not tracked by git. Never hand-edit; change `repo_metadata.py` instead.
- `gap_log.json` — append-only, machine-generated log of queries the bot couldn't answer from
  context. Treat as generated output (maintainers and Skill Updater read it); don't hand-edit
  entries, and don't delete history when adding new ones.
- `scripts/test_bot_routing.py`, `scripts/routing_smoke_check.py`,
  `scripts/test_link_and_issue_features.py` — routing/behavior checks, run directly with
  `python scripts/<name>.py`.
- `roadmap.md` — longer-term milestones; check before proposing large structural changes.

## Local Model Constraints (hard budget, not a nice-to-have)

Skill Bot runs `llama3.2` on a single local machine with tight, not generous, headroom
(8GB VRAM laptop GPU, often only a few GB of free system RAM). `OLLAMA_NUM_CTX` (env var,
default `4096`) is passed explicitly as `options.num_ctx` on every Ollama call in `bot.py` —
this is Ollama's own measured runtime default here, made explicit because it silently caps
system+prompt+response tokens per request. The target is expanding this bot across AOSSIE's
whole org (300+ repos), so:

- Any feature that grows per-request context (more skill files loaded, more Discord history,
  multi-turn memory, multi-PR summaries) must account for this budget explicitly — check the
  combined token cost of what gets loaded per query before adding to it. Docs outside `.agent/`
  are already capped (`OTHER_DOCS_BUDGET` in `repo_router.py`); keep new context under a cap too.
- Neither Ollama call currently round-trips the `context` token array, so requests are
  stateless across turns/threads today. If a future feature adds multi-turn continuity, key it
  per Discord thread ID — never share context across repos or threads.
- Prefer raising `OLLAMA_NUM_CTX` deliberately (it costs VRAM/RAM) over silently degrading
  answer quality by cramming more into a fixed window.

## Bar for a New Feature

Don't propose or build a Skill Bot capability from "this seems plausible" reasoning alone. Two
checks, in order:

1. **Evidence-grounded**: point to a concrete, logged example — a real `gap_log.json` entry, or
   a documented historical incident a maintainer can name and confirm. Don't speculate about
   what a contributor "might" ask.
2. **Real leverage, not just plausible**: a feature only clears the bar if it saves a maintainer
   real time on a *named, recurring* pain point — not something a maintainer could eyeball in
   seconds themselves (e.g. a checklist diff against `CONTRIBUTING.md` doesn't clear this bar).
   Prefer deterministic/mechanical checks (file-exists, grep-against-the-cloned-repo) over another
   LLM judgment call layered on an already-weak local model — e.g. verifying that
   files/functions referenced in a pasted PR or issue actually exist in the repo, which is
   AOSSIE's own most-cited pain point (hallucinated references in AI-assisted contributions).

## Contributing

- **Discord-first, mandatory**: all project communication happens on the
  [Discord server](https://discord.gg/hjUhu33uAn); post PR/issue updates there, not just on
  GitHub. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full workflow, branch/commit
  conventions, and pre-commit setup.
- **AI disclosure required**: if you used an AI tool for code, tests, or docs, say so in the PR
  description (tool + scope). See the
  [AI policy skill](https://github.com/AOSSIE-Org/Skills/blob/main/GIT-DIS-AIPolicy/SKILL.md) for
  the full policy — it also forbids unguided automatic issue/bug generation.
- **Code style**: PEP 8, type hints on new functions, docstrings on public functions/classes,
  no blocking sync calls in `async def` handlers (this is a `discord.py` + `httpx` async
  codebase), use the configured `logger` instead of `print`.
- Bold terms in AOSSIE's skill docs (e.g. **context load**, **gap signal**) are defined in the
  [Skills glossary](https://github.com/AOSSIE-Org/Skills/blob/main/GLOSSARY.md).
