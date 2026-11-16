# Privacy Policy

This policy covers the **Skill Bot** Discord bot: what it reads, what it keeps, and where data goes.

Skill Bot is self-hosted. Each copy is run by the people who set it up for their community (the
"operator"), on their own machine. There is no central Skill Bot service, and the Skill Bot
project does not receive any data from bots that other people run.

## What the bot reads

- **Messages in one help channel.** The operator chooses one channel (`DISCORD_CHANNEL_ID`). The
  bot reads messages posted there and in threads inside it.
- **Messages that @mention the bot**, in any channel it can see.
- **A few earlier messages in the same thread**, when it needs the context of a conversation
  (for example, the message you replied to).
- **Recent questions it missed.** When it starts, it reads recent messages in the help channel
  (by default the last 24 hours, set by `BACKLOG_MAX_AGE_HOURS`) to answer questions posted
  while it was offline.

It ignores messages from other bots. It does not read the server member list or anyone's online
status, and it does not ask for the Server Members or Presence intents.

## What it does with them

- It works out which repository a question is about, and answers it in a Discord thread using
  that repository's public documentation.
- Answers are written by a language model that runs **locally on the operator's machine**
  (Ollama). Message text is not sent to any third-party AI service.
- If a message contains a link to a GitHub issue or pull request, or to a Stack Overflow question,
  the bot fetches that public page from the GitHub or Stack Exchange API to help answer. Only the
  link is requested; your message is not sent to those sites.

## What it stores

- **Gap log (`gap_log.json`).** When the bot can't answer a question from the docs, it saves the
  question text, the time, a short reason code, and the Discord thread ID. It does not save your
  user ID or username. Maintainers read this file to find out which docs are missing. It stays on
  the operator's machine and is not committed to git.
- **Console logs.** While running, the bot prints each question it handles, with the author's
  Discord display name and username, to its console. These logs are not written to a file by
  Skill Bot itself. If an operator saves them, they stay on that operator's machine.

The bot does not sell, rent or share any of this data.

## GitHub issues (only when you ask)

If you explicitly ask the bot to open a GitHub issue (for example, "create an issue for this"), it
drafts the issue from the last few messages in the thread and posts it to the matching public
repository, with a line saying it was requested by your Discord display name. **That issue is
public.** The bot never opens issues on its own.

## Your choices

- Don't post in the help channel or mention the bot if you don't want it to read your message.
- To have your questions removed from a gap log, or to ask what a bot holds, contact the operator
  of that bot, usually the maintainers of the Discord server where it runs.
- To remove a GitHub issue the bot opened for you, ask the repository's maintainers.

## Changes

Changes to this policy are made in this file, and its git history shows what changed and when.
