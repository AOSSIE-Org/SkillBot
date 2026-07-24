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


def load_repo_context(repo_name: str, query: str = "") -> str:
    """Dynamically load and combine relevant context from the target repository based on query intent."""
    context_parts = []
    repo_path = get_repo_path(repo_name)
    if not repo_path:
        return ""

    context_parts.append(f"=== REPOSITORY: {repo_name} ===")
    q = query.lower()

    agent_dir = repo_path / ".agent"
    if agent_dir.exists():
        # 1. Operational Data (.agent/info/operational-data.md)
        ops_md = agent_dir / "info" / "operational-data.md"
        if ops_md.exists():
            try:
                with open(ops_md, "r", encoding="utf-8") as f:
                    context_parts.append(f"--- Operational Data (.agent/info/operational-data.md) ---\n{f.read()}")
            except Exception as e:
                logger.error(f"Error reading operational data file {ops_md}: {e}")

        # 3. DYNAMIC / CORE: Core Architecture (.agent/core/architecture.md)
        arch_keywords = ["arch", "architecture", "structure", "design", "component", "wrapper", "how it works", "flow", "pattern", "code", "file"]
        if not q or any(kw in q for kw in arch_keywords):
            arch_md = agent_dir / "core" / "architecture.md"
            if arch_md.exists():
                try:
                    with open(arch_md, "r", encoding="utf-8") as f:
                        context_parts.append(f"--- Core Architecture (.agent/core/architecture.md) ---\n{f.read()}")
                except Exception as e:
                    logger.error(f"Error reading architecture file {arch_md}: {e}")

        # 4. DYNAMIC LOAD: Instructions based on query intent (.agent/instructions/*.md)
        inst_dir = agent_dir / "instructions"
        if inst_dir.exists():
            setup_keywords = ["setup", "install", "build", "run", "env", "environment", "dependency", "dependencies", "npm", "yarn", "pnpm", "start", "dev"]
            testing_keywords = ["test", "testing", "jest", "spec", "coverage", "assert", "check"]
            deploy_keywords = ["deploy", "deployment", "ci", "cd", "release", "action", "workflow", "publish"]

            for md_file in sorted(inst_dir.glob("*.md")):
                fname = md_file.stem.lower()
                should_load = False

                if not q:
                    should_load = (fname == "setup")
                else:
                    if fname == "setup" and any(kw in q for kw in setup_keywords):
                        should_load = True
                    elif fname in ["testing", "test"] and any(kw in q for kw in testing_keywords):
                        should_load = True
                    elif fname in ["deployment", "ci-cd", "ci_cd"] and any(kw in q for kw in deploy_keywords):
                        should_load = True
                    elif fname in q:
                        should_load = True

                if should_load:
                    rel_path = md_file.relative_to(repo_path)
                    try:
                        with open(md_file, "r", encoding="utf-8") as f:
                            context_parts.append(f"--- Instruction ({rel_path}) ---\n{f.read()}")
                    except Exception as e:
                        logger.error(f"Error reading instruction file {md_file}: {e}")

    # 5. DYNAMIC LOAD: Local skills (skills/**/SKILL.md)
    skills_dir = repo_path / "skills"
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.rglob("**/SKILL.md")):
            skill_name = skill_file.parent.name.lower()
            if not q or skill_name in q:
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        context_parts.append(
                            f"--- Local Skill ({skill_file.parent.name}) ---\n{f.read()}"
                        )
                except Exception as e:
                    logger.error(f"Error reading {skill_file}: {e}")

    # 6. DYNAMIC LOAD: README.md if query asks for overview/readme
    readme_keywords = ["readme", "overview", "about", "description", "what is"]
    if not q or any(kw in q for kw in readme_keywords):
        readme_md = repo_path / "README.md"
        if readme_md.exists():
            try:
                with open(readme_md, "r", encoding="utf-8") as f:
                    content = f.read()
                    excerpt = content[:1500] + ("\n... (truncated)" if len(content) > 1500 else "")
                    context_parts.append(f"--- README.md ---\n{excerpt}")
            except Exception as e:
                logger.error(f"Error reading {readme_md}: {e}")

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
