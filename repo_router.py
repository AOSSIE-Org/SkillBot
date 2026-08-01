import asyncio
import logging
import re
import html
import httpx
import discord
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger("aossie-bot.router")

from repo_metadata import REPO_METADATA

# Non-GitHub domains SkillBot is allowed to fetch content from when a user pastes a link.
# Deliberately an allowlist, not "fetch anything" — fetching arbitrary user-supplied URLs
# server-side is an SSRF risk (e.g. a pasted http://169.254.169.254/... or http://localhost/...
# link). Restricting to known public developer-reference domains sidesteps that entirely,
# rather than trying to block private/internal IP ranges for an open-ended fetcher.
ALLOWED_EXTERNAL_DOMAINS = {"stackoverflow.com"}


def get_repo_details(repo_name: str) -> dict:
    """Get metadata for a repository directly from REPO_METADATA."""
    return REPO_METADATA.get(
        repo_name,
        {
            "url": "",
            "description": f"AOSSIE project: {repo_name}",
            "keywords": [repo_name.lower()],
        },
    )


def get_repo_from_thread_name(
    thread_name: str, available_repos: list[str]
) -> str | None:
    """Check if thread_name matches a repo name OR any of its keywords from REPO_METADATA."""
    norm_thread = re.sub(r"[\s\-_]", "", thread_name.lower())
    t_lower = thread_name.lower()

    for repo in available_repos:
        # 1. Match against repository key name (normalized)
        norm_repo = re.sub(r"[\s\-_]", "", repo.lower())
        if norm_repo and (norm_repo in norm_thread or norm_thread in norm_repo):
            return repo

        # 2. Match against keywords in REPO_METADATA for this repo
        details = get_repo_details(repo)
        for kw in details.get("keywords", []):
            kw_lower = kw.lower()
            kw_norm = re.sub(r"[\s\-_]", "", kw_lower)
            if kw_lower in t_lower or (len(kw_norm) > 3 and kw_norm in norm_thread):
                return repo

    return None


def get_available_repos() -> list[str]:
    """Return available client repositories strictly from REPO_METADATA."""
    return sorted(list(REPO_METADATA.keys()))


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
    """Detect matching repository based on case-insensitive keyword mappings and normalization."""
    q_lower = query.lower()
    q_norm = re.sub(r"[\s\-_]", "", q_lower)

    for repo in available_repos:
        norm_repo = re.sub(r"[\s\-_]", "", repo.lower())
        if norm_repo and norm_repo in q_norm:
            return repo

        details = get_repo_details(repo)
        for kw in details["keywords"]:
            kw_lower = kw.lower()
            kw_norm = re.sub(r"[\s\-_]", "", kw_lower)
            if kw_lower in q_lower or (len(kw_norm) > 3 and kw_norm in q_norm):
                return repo
    return None


async def classify_repo_with_llm(
    query: str, available_repos: list[str], ollama_model: str, ollama_url: str, num_ctx: int = 4096
) -> str | None:
    """Use Ollama LLM to classify which repository is being discussed."""
    if not available_repos:
        return None

    prompt = (
        "You are a routing assistant. Based on the user's message, determine which project/repository they are talking about.\n"
        "Available repositories:\n"
        + "\n".join([f"- {r}" for r in available_repos])
        + "\n\n"
        f"User message: \"{query}\"\n\n"
        "Reply with ONLY the exact name of the repository from the list above. "
        "If the user is not referring to any specific repository, or if it is unclear, reply with 'none'. "
        "Do not include any explanation or other text."
    )

    try:
        payload = {
            "model": ollama_model,
            "prompt": prompt,
            "system": "You are a strict routing classifier. Output ONLY a repository name or 'none'. No explanation, no intro, no punctuation.",
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": num_ctx},
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
        logger.exception(f"Error classifying repository with LLM: {e}")

    return None


def _keyword_hit(text: str, keyword: str) -> bool:
    """Word-boundary match for a single keyword/phrase against already-lowercased text.
    Plain substring checks (e.g. "how" in q) false-positive on "however"/"somehow"/"show", pulling
    in extra context (README dumps, instruction files) for queries that never mentioned the topic."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def load_repo_context(repo_name: str, query: str = "") -> str:
    """Dynamically load context: ALWAYS load operational-data.md and architecture.md,
    and dynamically load specific instruction/core files based on user query intent."""
    context_parts = []
    repo_path = get_repo_path(repo_name)
    if not repo_path:
        return ""

    context_parts.append(f"=== REPOSITORY: {repo_name} ===")
    q = query.lower()

    agent_dir = repo_path / ".agent"
    if agent_dir.exists():
        # 1. ALWAYS LOAD: Operational Data (.agent/info/operational-data.md)
        ops_md = agent_dir / "info" / "operational-data.md"
        if ops_md.exists():
            try:
                with open(ops_md, "r", encoding="utf-8") as f:
                    context_parts.append(f"--- Operational Data (.agent/info/operational-data.md) ---\n{f.read()}")
            except Exception as e:
                logger.error(f"Error reading operational data file {ops_md}: {e}")

        # 2. ALWAYS LOAD: Core Architecture (.agent/core/architecture.md)
        arch_md = agent_dir / "core" / "architecture.md"
        if arch_md.exists():
            try:
                with open(arch_md, "r", encoding="utf-8") as f:
                    context_parts.append(f"--- Core Architecture (.agent/core/architecture.md) ---\n{f.read()}")
            except Exception as e:
                logger.error(f"Error reading architecture file {arch_md}: {e}")

        # 3. DYNAMIC INTENT DETECTION: Core Files (code-mapping, edge-cases, examples)
        core_dir = agent_dir / "core"
        if core_dir.exists():
            mapping_keywords = ["map", "mapping", "file", "path", "code-mapping", "location", "tree"]
            edge_keywords = ["edge", "boundary", "limit", "edge-case", "fallback", "handling", "exception"]
            example_keywords = ["example", "sample", "usage", "demo", "snippet", "how to use"]

            for core_file in sorted(core_dir.glob("*.md")):
                fname = core_file.stem.lower()
                if fname == "architecture":
                    continue  # Already loaded above

                should_load = False
                if fname in ["code-mapping", "code_mapping"] and any(_keyword_hit(q, kw) for kw in mapping_keywords):
                    should_load = True
                elif fname in ["edge-cases", "edge_cases"] and any(_keyword_hit(q, kw) for kw in edge_keywords):
                    should_load = True
                elif fname in ["examples", "example"] and any(_keyword_hit(q, kw) for kw in example_keywords):
                    should_load = True
                elif _keyword_hit(q, fname):
                    should_load = True

                if should_load:
                    rel_path = core_file.relative_to(repo_path)
                    try:
                        with open(core_file, "r", encoding="utf-8") as f:
                            context_parts.append(f"--- Core Context ({rel_path}) ---\n{f.read()}")
                    except Exception as e:
                        logger.error(f"Error reading core file {core_file}: {e}")

        # 4. DYNAMIC INTENT DETECTION: Instructions (.agent/instructions/*.md)
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
                    if fname == "setup" and any(_keyword_hit(q, kw) for kw in setup_keywords):
                        should_load = True
                    elif fname in ["testing", "test"] and any(_keyword_hit(q, kw) for kw in testing_keywords):
                        should_load = True
                    elif fname in ["deployment", "ci-cd", "ci_cd"] and any(_keyword_hit(q, kw) for kw in deploy_keywords):
                        should_load = True
                    elif _keyword_hit(q, fname):
                        should_load = True

                if should_load:
                    rel_path = md_file.relative_to(repo_path)
                    try:
                        with open(md_file, "r", encoding="utf-8") as f:
                            context_parts.append(f"--- Instruction ({rel_path}) ---\n{f.read()}")
                    except Exception as e:
                        logger.error(f"Error reading instruction file {md_file}: {e}")

    # 5. DYNAMIC INTENT DETECTION: Local Skills (skills/**/SKILL.md)
    skills_dir = repo_path / "skills"
    if skills_dir.exists():
        for skill_file in sorted(skills_dir.rglob("**/SKILL.md")):
            skill_name = skill_file.parent.name.lower()
            if not q or _keyword_hit(q, skill_name):
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        context_parts.append(
                            f"--- Local Skill ({skill_file.parent.name}) ---\n{f.read()}"
                        )
                except Exception as e:
                    logger.error(f"Error reading {skill_file}: {e}")

    # 6. DYNAMIC INTENT DETECTION: README.md
    readme_keywords = ["readme", "overview", "about", "description", "what is", "how", "help"]
    if not q or any(_keyword_hit(q, kw) for kw in readme_keywords):
        readme_md = repo_path / "README.md"
        if readme_md.exists():
            try:
                with open(readme_md, "r", encoding="utf-8") as f:
                    content = f.read()
                    excerpt = content[:2000] + ("\n... (truncated)" if len(content) > 2000 else "")
                    context_parts.append(f"--- README.md ---\n{excerpt}")
            except Exception as e:
                logger.error(f"Error reading {readme_md}: {e}")

    # 7. DYNAMIC INTENT DETECTION: Org-Wide Skills (org-wide-skills/*/SKILL.md)
    org_skills_dir = Path("org-wide-skills")
    if not org_skills_dir.exists():
        org_skills_dir = repo_path.parent.parent / "org-wide-skills"

    if org_skills_dir.exists():
        mcp_keywords = ["mcp", "github", "playwright", "puppeteer", "external link", "link", "pr", "issue", "http", "https", "browser", "ui test", "test ui"]
        for skill_dir in org_skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    s_name = skill_dir.name.lower()
                    should_load_org_skill = False
                    if s_name == "mcp-integration" and any(_keyword_hit(q, kw) for kw in mcp_keywords):
                        should_load_org_skill = True
                    elif _keyword_hit(q, s_name):
                        should_load_org_skill = True

                    if should_load_org_skill:
                        try:
                            with open(skill_file, "r", encoding="utf-8") as f:
                                context_parts.append(f"--- Org-Wide Skill ({skill_dir.name}) ---\n{f.read()}")
                        except Exception as e:
                            logger.error(f"Error reading org skill {skill_file}: {e}")

    return "\n\n".join(context_parts)


async def fetch_github_link_info(url: str) -> str | None:
    """Fetch GitHub PR or Issue details via GitHub REST API."""
    match = re.search(r"https?://github\.com/([^/]+)/([^/]+)/(pull|issues)/(\d+)", url, re.IGNORECASE)
    if not match:
        return None

    owner, repo, item_type_raw, number = match.groups()
    item_type = "pulls" if item_type_raw.lower() == "pull" else "issues"
    api_url = f"https://api.github.com/repos/{owner}/{repo}/{item_type}/{number}"

    headers = {"User-Agent": "SkillBot", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(api_url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                title = data.get("title", "No Title")
                author = data.get("user", {}).get("login", "Unknown")
                state = data.get("state", "unknown")
                body = data.get("body") or ""
                body_clean = body[:500].strip() + ("..." if len(body) > 500 else "")
                is_pr = (item_type == "pulls")

                info = (
                    f"--- Fetched GitHub {'PR' if is_pr else 'Issue'} #{number} Details ---\n"
                    f"URL: {data.get('html_url', url)}\n"
                    f"Repository: {owner}/{repo}\n"
                    f"Title: {title}\n"
                    f"Author: {author}\n"
                    f"State: {state}\n"
                )
                if is_pr and "merged" in data:
                    info += f"Merged: {data.get('merged')}\n"
                if body_clean:
                    info += f"Description: {body_clean}\n"

                return info
            else:
                logger.warning(f"GitHub API returned HTTP {res.status_code} for {api_url}")
    except Exception as e:
        logger.error(f"Error fetching GitHub link info for {url}: {e}")

    return None


def _is_allowed_domain(url: str) -> bool:
    """Check a URL's host against ALLOWED_EXTERNAL_DOMAINS (exact match or subdomain)."""
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_EXTERNAL_DOMAINS)


async def fetch_stackoverflow_info(url: str, max_chars: int = 800) -> str | None:
    """Fetch a Stack Overflow question + top answer via the official Stack Exchange API.

    NOT scraped from stackoverflow.com directly — that's behind a Cloudflare JS challenge
    ("Just a moment...") that a plain HTTP GET can never pass, regardless of headers (confirmed
    empirically: identical 403 with both a bare and a full browser User-Agent). The public
    api.stackexchange.com API returns the same content as clean JSON with no such block, and
    matches the GitHub-API-not-scraping pattern already used elsewhere in this file."""
    match = re.search(r"stackoverflow\.com/questions/(\d+)", url)
    if not match:
        return None
    question_id = match.group(1)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            q_res = await client.get(
                f"https://api.stackexchange.com/2.3/questions/{question_id}",
                params={"site": "stackoverflow", "filter": "withbody"},
            )
            a_res = await client.get(
                f"https://api.stackexchange.com/2.3/questions/{question_id}/answers",
                params={"site": "stackoverflow", "sort": "votes", "order": "desc", "filter": "withbody"},
            )

        parts = []
        if q_res.status_code == 200:
            items = q_res.json().get("items") or []
            if items:
                title = html.unescape(items[0].get("title", ""))
                body_html = items[0].get("body", "")
                body_text = BeautifulSoup(body_html, "html.parser").get_text(" ", strip=True)
                parts.append(f"Question: {title}\n{body_text}")
        if a_res.status_code == 200:
            items = a_res.json().get("items") or []
            if items:
                answer_html = items[0].get("body", "")
                answer_text = BeautifulSoup(answer_html, "html.parser").get_text(" ", strip=True)
                parts.append(f"Top Answer (score {items[0].get('score', '?')}): {answer_text}")

        if not parts:
            return None
        text = "\n\n".join(parts)
        text = text[:max_chars] + ("..." if len(text) > max_chars else "")
        return f"--- Fetched Stack Overflow Q{question_id} ---\n{text}"
    except Exception as e:
        logger.error(f"Error fetching Stack Overflow question {question_id}: {e}")
    return None


async def fetch_generic_link_info(url: str, max_chars: int = 800) -> str | None:
    """Fetch and extract readable content from an allowlisted non-GitHub, non-Stack-Overflow
    URL, via generic HTML tag-stripping.

    Truncates hard — this runs on a small local model with a tight context budget, so raw HTML
    (nav/ads/sidebars) would waste most of it on noise. Note: sites behind a JS/Cloudflare
    challenge (like stackoverflow.com's HTML pages) will simply fail here — this path only
    works for plain server-rendered pages; use a dedicated API-based fetch (as done for Stack
    Overflow above) for any future domain that blocks direct scraping."""
    if not _is_allowed_domain(url):
        return None
    if "stackoverflow.com" in (urlparse(url).hostname or ""):
        return await fetch_stackoverflow_info(url, max_chars)

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.get(url, headers={"User-Agent": "SkillBot"})
            if res.status_code != 200:
                logger.warning(f"Generic link fetch returned HTTP {res.status_code} for {url}")
                return None

            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = soup.get_text(" ", strip=True)

            if not text:
                return None

            text = text[:max_chars] + ("..." if len(text) > max_chars else "")
            return f"--- Fetched Page: {url} ---\n{text}"
    except Exception as e:
        logger.error(f"Error fetching generic link {url}: {e}")

    return None


async def extract_and_fetch_external_links(text: str) -> str:
    """Extract URLs from text, fetch GitHub PR/Issue info + allowlisted page content,
    and return enriched context without duplicates."""
    urls = re.findall(r"https?://[^\s>]+", text)
    if not urls:
        return ""

    MAX_LINKS = 5
    seen_urls = set()
    github_urls = []
    generic_urls = []
    for url in urls:
        normalized_url = url.rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        url_lower = url.lower()
        if "github.com" in url_lower and ("/pull/" in url_lower or "/issues/" in url_lower):
            github_urls.append(url)
        elif _is_allowed_domain(url):
            generic_urls.append(url)

    fetched_parts = []
    if github_urls:
        results = await asyncio.gather(
            *(fetch_github_link_info(u) for u in github_urls[:MAX_LINKS])
        )
        fetched_parts.extend([info for info in results if info])

    remaining_slots = MAX_LINKS - len(fetched_parts)
    if generic_urls and remaining_slots > 0:
        results = await asyncio.gather(
            *(fetch_generic_link_info(u) for u in generic_urls[:remaining_slots])
        )
        fetched_parts.extend([info for info in results if info])

    if fetched_parts:
        return "\n".join(fetched_parts)
    return ""


def get_repo_full_name(repo_name: str) -> str | None:
    """Extract 'owner/repo' from REPO_METADATA's url field (ignores any /tree/<branch> suffix)."""
    url = get_repo_details(repo_name).get("url", "")
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url, re.IGNORECASE)
    if match:
        owner, repo = match.groups()
        return f"{owner}/{repo}"
    return None


async def fetch_github_issue_comments(owner: str, repo: str, number: str, max_comments: int = 5) -> str:
    """Fetch up to max_comments comments from an existing GitHub PR/Issue — used to give the
    issue-drafting step real discussion context instead of just the last few Discord lines."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    headers = {"User-Agent": "SkillBot", "Accept": "application/vnd.github.v3+json"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(api_url, headers=headers, params={"per_page": max_comments})
            if res.status_code == 200:
                lines = []
                for c in res.json()[:max_comments]:
                    author = c.get("user", {}).get("login", "unknown")
                    body = (c.get("body") or "")[:300].strip()
                    if body:
                        lines.append(f"- {author}: {body}")
                if lines:
                    return "--- Existing Discussion Comments (#" + number + ") ---\n" + "\n".join(lines)
            else:
                logger.warning(f"GitHub comments API returned HTTP {res.status_code} for {api_url}")
    except Exception as e:
        logger.error(f"Error fetching comments for {owner}/{repo}#{number}: {e}")
    return ""


async def create_github_issue(repo_full_name: str, title: str, body: str) -> str | None:
    """Create a GitHub issue via the gh CLI. Returns the created issue URL, or None on failure.
    Uses exec (argv list, no shell) so title/body never need escaping and can't be injected."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "issue", "create",
            "--repo", repo_full_name,
            "--title", title,
            "--body", body,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
        logger.error(f"gh issue create failed for {repo_full_name}: {stderr.decode().strip()}")
    except FileNotFoundError:
        logger.error("gh CLI not found on this machine — cannot create issues.")
    except Exception as e:
        logger.error(f"Error creating GitHub issue in {repo_full_name}: {e}")
    return None


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
