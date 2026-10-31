import os
import sys
import re
import logging
import httpx
from pathlib import Path

# Add parent directory to sys.path to import repo_metadata
script_dir = Path(__file__).resolve().parent
bot_root = script_dir.parent
sys.path.insert(0, str(bot_root))

from dotenv import load_dotenv
from repo_metadata import REPO_METADATA

load_dotenv(bot_root / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("subtree-sync")

# Copied when a repository's entry in repo_metadata.py has no "docs" list.
DEFAULT_DOCS = ["README.md"]
MAX_FILE_BYTES = 200_000


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Parse owner, repo, and ref from GitHub URL."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+))?", url)
    if match:
        owner, repo, ref = match.groups()
        repo = repo.removesuffix(".git")
        ref = ref or "main"
        return owner, repo, ref
    return "", "", "main"


def resolve_doc_paths(docs: list[str], owner: str, repo: str, ref: str, client: httpx.Client) -> list[str]:
    """Turn the "docs" entries into file paths: a path ending in .md is one file, anything
    else is a folder whose .md files are all copied ("." means the whole repository)."""
    files = [d for d in docs if d.lower().endswith(".md")]
    folders = [d.strip("/") for d in docs if not d.lower().endswith(".md")]
    if not folders:
        return files

    # One API call lists the whole repository; only made when a folder is requested.
    res = client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}", params={"recursive": "1"})
    res.raise_for_status()
    data = res.json()
    if data.get("truncated"):
        # A partial listing would make the cleanup below delete docs that still exist.
        raise ValueError(f"GitHub truncated the file list of {owner}/{repo}@{ref} (repository too large); "
                         "list single .md files in \"docs\" instead of folders")
    for entry in data.get("tree", []):
        path = entry["path"]
        if entry["type"] != "blob" or not path.lower().endswith(".md") or entry.get("size", 0) > MAX_FILE_BYTES:
            continue
        if any(folder in ("", ".") or path.startswith(folder + "/") for folder in folders):
            files.append(path)
    return sorted(set(files))


def sync_repo_context(repo_name: str, meta: dict, client: httpx.Client) -> bool:
    """Fetch the repository's "docs" files directly from the raw GitHub endpoint."""
    url = meta.get("url")
    if not url:
        logger.warning(f"No URL defined for {repo_name}, skipping.")
        return False

    owner, repo, ref = parse_github_url(url)
    if not owner or not repo:
        logger.error(f"Invalid GitHub URL for {repo_name}: {url}")
        return False

    logger.info(f"Syncing context for '{repo_name}' ({owner}/{repo}@{ref})...")
    target_dir = bot_root / "repos" / repo_name
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc_paths = resolve_doc_paths(meta.get("docs", DEFAULT_DOCS), owner, repo, ref, client)
    except (httpx.HTTPError, ValueError) as e:
        logger.error(f"Cannot list files for {repo_name}, keeping the previous copy: {e}")
        return False

    downloaded_files = set()
    errors = 0
    for rel_file in doc_paths:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rel_file}"
        try:
            res = client.get(raw_url)
            if res.status_code == 200:
                dest_path = target_dir / rel_file
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(res.content)
                downloaded_files.add(rel_file)
            elif res.status_code == 404:
                logger.warning(f"Not found in {repo_name}: {rel_file} (check \"docs\" in repo_metadata.py)")
            else:
                logger.warning(f"HTTP {res.status_code} fetching {rel_file} for {repo_name}")
                errors += 1
        except httpx.HTTPError as e:
            logger.error(f"Transport error fetching {rel_file} for {repo_name}: {e}")
            errors += 1

    # Deletion policy: remove local files that are no longer listed. Skipped after an error,
    # so a network problem never empties the bot's copy.
    if not errors:
        for p in list(target_dir.rglob("*")):
            if p.is_file() and p.relative_to(target_dir).as_posix() not in downloaded_files:
                try:
                    p.unlink()
                    logger.info(f"Removed stale local file: repos/{repo_name}/{p.relative_to(target_dir).as_posix()}")
                except Exception as e:
                    logger.warning(f"Failed to remove stale file {p}: {e}")

    logger.info(f"Synced {len(downloaded_files)} files into repos/{repo_name}")
    return bool(downloaded_files) and not errors


def sync_all_subtrees():
    os.chdir(bot_root)
    repos_dir = bot_root / "repos"
    repos_dir.mkdir(exist_ok=True)

    headers = {"User-Agent": "SkillBot-Context-Sync"}
    # Optional: GitHub allows 60 API requests an hour without a token. Folder entries in
    # "docs" use one request per repository per sync.
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"

    success_count = 0
    total_count = len(REPO_METADATA)

    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
        for repo_name, meta in REPO_METADATA.items():
            if sync_repo_context(repo_name, meta, client):
                success_count += 1

    logger.info(f"Subtree sync completed: {success_count}/{total_count} repositories synced successfully.")


if __name__ == "__main__":
    sync_all_subtrees()
