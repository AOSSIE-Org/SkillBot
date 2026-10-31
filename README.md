<div align="center">
  <img src="public/skill_logo.png" alt="Skill Bot logo" width="175" />

<h1>Skill Bot</h1>
<h3>A free, local Discord bot that answers contributor questions from your repositories' own docs</h3>
</div>

**Skill Bot** is a Discord bot that answers contributors' questions about your project's repositories, using each repository's own Markdown docs as its source.

It works for any organization or project that uses Discord. It runs on a local model, so there are no API fees and no rate limits.

* **Why:** contributors ask the same setup and "where do I start" questions again and again on Discord, and maintainers spend their time repeating answers that are already written down.
* **Who:** open-source communities, and any team that talks to contributors on Discord.
* **What:** a bot that works out which repository a question is about, picks the docs from that repository that match the question, and answers with a local model (Ollama).
* **How:** list your repositories and their docs in `repo_metadata.py`, add a Discord token, and run `bot.py`.

At startup and once a day, it copies the docs you listed from each repository into `repos/`. For each question it sends the local model only the files that question needs, so it runs well on an ordinary computer.

---

## 🚀 Key Features

* **Repository Routing**: Detects which repository a question is about from its name and keywords, falling back to local LLM classification.
* **Small Prompts for Local Models**: Sends only the docs whose names match the question, within a fixed size budget, however many docs you list.
* **Thread-per-Query**: Every new question gets its own Discord thread, so the main channel stays clean and history stays scoped.
* **Clarifying Questions**: Asks a focused follow-up when a question is ambiguous, before answering.
* **Fully Local Inference**: Uses a local Ollama model (such as `llama3.2` or `qwen2.5:7b`). No contributor data leaves the machine and there are no API costs.
* **Startup Backlog Recovery**: On startup, answers questions posted while the bot was offline.
* **Gap Log**: Questions it couldn't route to a repository, or found no docs for, are appended to `gap_log.json`, a plain JSON file maintainers can read to see which docs are missing.

---

## 💻 Tech Stack

* **Discord Bot Framework**: Discord.py (with Message Content Intent enabled)
* **Local Model Server**: Ollama
* **Programming Language**: Python 3.10+
* **HTTP Client**: httpx (async requests to Ollama API)
* **Configuration & Environment**: dotenv (dotenv-based configuration)

---

## 🏁 Set Up Skill Bot for Your Organization

You need a machine that stays on (a server, a spare PC, or your own computer) to run the bot and the local model.

### 1. Make your copy

Click **Use this template** at the top of this page and create a copy in your organization (for example `your-org/skillbot`). Clone it on the machine that will run the bot:

```bash
git clone https://github.com/your-org/skillbot.git
cd skillbot
```

### 2. List your repositories and their docs

Open [`repo_metadata.py`](./repo_metadata.py) and replace the example entry with your repositories:

```python
REPO_METADATA = {
    "EduAid": {
        "url": "https://github.com/your-org/EduAid",       # add /tree/<branch> for another branch
        "description": "Generates quizzes from any text",   # shown when the bot asks which project
        "keywords": ["quiz", "quiz generator"],             # optional; the name already matches
        "docs": ["README.md", "CONTRIBUTING.md", "docs/"],  # optional; defaults to ["README.md"]
    },
}
```

In `docs`, a path ending in `.md` copies that one file, and any other path copies every `.md` file in that folder.

* **List only the repositories contributors ask about.** Every entry is one more option the local model has to choose between when a question doesn't name a project, so a short list gives better answers than your whole organization.
* **A shared skills or policies repository is just another entry.** Give it keywords such as `"onboarding"` or `"ai policy"` so those questions reach it.

Commit the change, so your copy keeps your list. To check it, run `python scripts/update_subtrees.py`: it copies the docs into `repos/` and warns about any path it can't find.

### 3. Name docs so the bot can find them

The bot doesn't send every copied doc to the model. For each question it sends:

| Doc | When |
|---|---|
| `README.md` | Overview questions ("what is", "how", "help"), first 2,000 characters |
| A doc whose file or folder name matches the question | For example, `CONTRIBUTING.md` for "how do I contribute?", `docs/setup.md` for "how do I install it?", `testing.md` for test questions |

Other matched docs are capped at 2,000 characters each and 4,000 in total, so a long `docs` list never slows the model down. Clear file names (`setup.md`, `testing.md`, `deployment.md`, `architecture.md`, `CONTRIBUTING.md`) get the best results.

Repositories that use the `.agent/` layout (`.agent/info/operational-data.md`, `.agent/core/architecture.md`, `.agent/instructions/*.md`) can list `".agent"` in `docs`. Those two files are then sent with every question, and the instruction files when the question is about them.

### 4. Install Python and the local model

* **Python 3.10+**
* **[Ollama](https://ollama.com/download)**, then pull a model: `ollama pull llama3.2`
* Optional: the **[GitHub CLI](https://cli.github.com/)**, logged in with `gh auth login`, if you want contributors to be able to ask the bot to open issues.

```bash
python -m venv venv
source venv/bin/activate        # Windows (PowerShell): .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 5. Create the Discord bot

1. In the [Discord Developer Portal](https://discord.com/developers/applications), click **New Application**, open **Bot**, and turn on **Message Content Intent**. Copy the bot token.
2. Under **OAuth2 → URL Generator**, tick the `bot` scope and these permissions: View Channels, Send Messages, Create Public Threads, Send Messages in Threads, Read Message History. Open the generated link to add the bot to your server.
3. In Discord, turn on **Settings → Advanced → Developer Mode**, then right-click the channel where contributors ask questions and choose **Copy Channel ID**.

### 6. Configure

```bash
cp .env.example .env
```

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_channel_id
ORG_NAME=Your Org               # optional: your organization's name, used in the model's instructions
```

Other settings, all optional, are described in [`.env.example`](./.env.example): the model (`OLLAMA_MODEL`), its context size (`OLLAMA_NUM_CTX`), and how often docs are refreshed (`SYNC_INTERVAL_HOURS`).

### 7. Run

```bash
python bot.py
```

On startup the bot copies the docs into `repos/`, then answers questions in the channel. It refreshes them every 24 hours. On Windows, `start_bot_hidden.vbs` runs it in the background.

### Keeping it useful

* **Read `gap_log.json`.** It lists questions the bot couldn't route or had no docs for, which tells you which docs to write next, or which keyword to add to `repo_metadata.py`.
* **Get updates** by pulling from the Skill Bot repository you made your copy from: `git remote add upstream <its URL>`, then `git pull upstream main`. `repos/` is not tracked by git, so updates never touch your docs. If `repo_metadata.py` conflicts, keep your version.

---

## 🗺️ Roadmap

Planned work is listed in [roadmap.md](./roadmap.md).

---

## 🙌 Contributing

Contributions are welcome. See the [Contribution Guidelines](./CONTRIBUTING.md).

---

## 📍 License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.
