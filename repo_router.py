import logging
import re
import httpx
import discord
from pathlib import Path

logger = logging.getLogger("aossie-bot.router")

from repo_metadata import REPO_METADATA


def get_repo_details(repo_name: str) -> dict:
    """Get metadata for a repository, with fallback default values."""
    return REPO_METADATA.get(
        repo_name,
        {
            "url": f"https://github.com/AOSSIE-Org/{repo_name}",
            "description": f"AOSSIE project: {repo_name}",
            "keywords": [repo_name.lower()],
        },
    )


def get_repo_from_thread_name(
    thread_name: str, available_repos: list[str]
) -> str | None:
    """Check if any available repo name is in the thread name (case-insensitive)."""
    for repo in available_repos:
        if repo.lower() in thread_name.lower():
            return repo
    return None


def get_available_repos() -> list[str]:
    """Dynamically discover available client repositories in subtrees or workspace."""
    search_dirs = [Path("repos"), Path("."), Path("..")]
    repos = set()

    for base_dir in search_dirs:
        if not base_dir.exists():
            continue
        for item in base_dir.iterdir():
            if item.is_dir():
                if item.name in ["SkillBot", "skills", "repos"] or item.name.startswith("."):
                    continue
                if (
                    (item / "AGENTS.md").exists()
                    or (item / ".agent").exists()
                    or (item / ".clinerules").exists()
                    or (item / ".git").exists()
                ):
                    repos.add(item.name)

    return sorted(list(repos))


def get_repo_path(repo_name: str) -> Path | None:
    """Locate the path of a repository across subtrees and workspace locations."""
    candidates = [
        Path("repos") / repo_name,
        Path(repo_name),
        Path("..") / repo_name,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def detect_repo_by_keywords(query: str, available_repos: list[str]) -> str | None:
    """Detect matching repository based on case-insensitive keyword mappings."""
    q = query.lower()

    for repo in available_repos:
        details = get_repo_details(repo)
        for kw in details["keywords"]:
            if kw in q:
                return repo
    return None


async def classify_repo_with_llm(
    query: str, available_repos: list[str], ollama_model: str, ollama_url: str
) -> str | None:
    """Use Ollama LLM to classify which repository is being discussed."""
    if not available_repos:
        return None

    prompt = (
        f"You are a routing assistant. Based on the user's message, determine which project/repository they are talking about.\n"
        f"Available repositories:\n"
        + "\n".join([f"- {r}" for r in available_repos])
        + "\n\n"
        f"User message: \"{query}\"\n\n"
        f"Reply with ONLY the exact name of the repository from the list above. "
        f"If the user is not referring to any specific repository, or if it is unclear, reply with 'none'. "
        f"Do not include any explanation or other text."
    )

    try:
        payload = {
            "model": ollama_model,
            "prompt": prompt,
            "system": "You are a strict routing classifier. Output ONLY a repository name or 'none'. No explanation, no intro, no punctuation.",
            "stream": False,
            "options": {"temperature": 0.0},
        }
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(ollama_url, json=payload)
            response.raise_for_status()
            res_text = response.json().get("response", "").strip()
            # Clean up punctuation
            res_text = re.sub(r"['\"`.]", "", res_text).strip()

            for repo in available_repos:
                if res_text.lower() == repo.lower():
                    return repo
    except Exception as e:
        logger.error(f"Error classifying repository with LLM: {e}")

    return None


def load_repo_context(repo_name: str) -> str:
    """Load and combine context from the target repository to guide the local LLM."""
    context_parts = []
    repo_path = get_repo_path(repo_name)
    if not repo_path:
        return ""

    context_parts.append(f"=== REPOSITORY: {repo_name} ===")

    # 1. Load local AGENTS.md
    agents_md = repo_path / "AGENTS.md"
    if agents_md.exists():
        try:
            with open(agents_md, "r", encoding="utf-8") as f:
                context_parts.append(f"--- AGENTS.md ---\n{f.read()}")
        except Exception as e:
            logger.error(f"Error reading {agents_md}: {e}")

    # 2. Load all .md files in .agent/ recursively
    agent_dir = repo_path / ".agent"
    if agent_dir.exists():
        for md_file in sorted(agent_dir.rglob("*.md")):
            rel_path = md_file.relative_to(repo_path)
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    context_parts.append(f"--- Instructions: {rel_path} ---\n{f.read()}")
            except Exception as e:
                logger.error(f"Error reading instruction file {md_file}: {e}")

    # 3. Load README.md if present
    readme_md = repo_path / "README.md"
    if readme_md.exists():
        try:
            with open(readme_md, "r", encoding="utf-8") as f:
                content = f.read()
                # Excerpt up to 2000 chars if long
                excerpt = content[:2000] + ("\n... (truncated)" if len(content) > 2000 else "")
                context_parts.append(f"--- README.md ---\n{excerpt}")
        except Exception as e:
            logger.error(f"Error reading {readme_md}: {e}")

    # 4. Load local skills
    skills_dir = repo_path / "skills"
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.rglob("**/SKILL.md")):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    context_parts.append(
                        f"--- Local Skill: {skill_file.parent.name} ---\n{f.read()}"
                    )
            except Exception as e:
                logger.error(f"Error reading {skill_file}: {e}")

    return "\n\n".join(context_parts)


async def send_clarification_request(
    thread: discord.Thread, available_repos: list[str]
):
    """Politely ask the user to clarify which project they need help with."""
    repos_lines = []
    for repo in available_repos:
        details = get_repo_details(repo)
        repos_lines.append(
            f"- **{repo}** ([GitHub Link]({details['url']})): {details['description']}"
        )

    repos_list = "\n".join(repos_lines)
    msg = (
        f"I'm not sure which repository you are referring to. Could you please specify which project you need help with?\n\n"
        f"Available projects:\n{repos_list}\n\n"
        f"Simply mention the project name in your next reply."
    )
    await thread.send(msg)
