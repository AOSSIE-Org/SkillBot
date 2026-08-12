import os
import re
import sys
import logging
import httpx
from pathlib import Path

# Add parent directory to sys.path to import repo_metadata
script_dir = Path(__file__).resolve().parent
bot_root = script_dir.parent
sys.path.insert(0, str(bot_root))

from repo_metadata import REPO_METADATA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("subtree-sync")

# Key context files to sync from remote client repositories
KNOWN_CONTEXT_FILES = [
    ".agent/info/operational-data.md",
    ".agent/core/architecture.md",
    ".agent/instructions/setup.md",
    ".agent/instructions/testing.md",
    ".agent/instructions/deployment.md",
    ".agent/instructions/format-guide.md",
    ".agent/instructions/checklist.md",
    ".agent/instructions/bad-patterns.md",
    "references/checklist.md",
    "references/format-guide.md",
    "references/bad-patterns.md",
    "SKILL.md",
    "AGENTS.md",
    "README.md",
]


REQUIRED_CONTEXT_FILES = {
    ".agent/info/operational-data.md",
    ".agent/core/architecture.md",
    "README.md",
}


def parse_github_url(url: str) -> tuple[str, str, str]:
    """Parse owner, repo, and ref from GitHub URL."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+))?", url)
    if match:
        owner, repo, ref = match.groups()
        repo = repo.removesuffix(".git")
        ref = ref or "main"
        return owner, repo, ref
    return "", "", "main"


def sync_repo_context(repo_name: str, meta: dict, client: httpx.Client) -> bool:
    """Fetch specified .agent context files directly from raw GitHub endpoint."""
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

    headers = {"User-Agent": "SkillBot-Context-Sync"}
    downloaded_files = set()
    failed_required = []
    http_errors = 0
    transport_errors = 0

    for rel_file in KNOWN_CONTEXT_FILES:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{rel_file}"
        try:
            res = client.get(raw_url, headers=headers)
            if res.status_code == 200:
                dest_path = target_dir / rel_file
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(res.content)
                logger.info(f"Downloaded: repos/{repo_name}/{rel_file}")
                downloaded_files.add(rel_file)
            elif res.status_code == 404:
                logger.debug(f"File not found on remote (404): {rel_file} for {repo_name}")
                if rel_file in REQUIRED_CONTEXT_FILES:
                    logger.error(f"Required file missing (404) for {repo_name}: {rel_file}")
                    failed_required.append(rel_file)
            else:
                logger.warning(f"HTTP {res.status_code} fetching {rel_file} for {repo_name}")
                http_errors += 1
                if rel_file in REQUIRED_CONTEXT_FILES:
                    failed_required.append(rel_file)
        except Exception as e:
            logger.error(f"Transport error fetching {rel_file} for {repo_name}: {e}")
            transport_errors += 1
            if rel_file in REQUIRED_CONTEXT_FILES:
                failed_required.append(rel_file)

    # Deletion policy: remove local files absent from KNOWN_CONTEXT_FILES or not downloaded in current sync
    known_set = set(KNOWN_CONTEXT_FILES)
    if target_dir.exists():
        for p in list(target_dir.rglob("*")):
            if p.is_file():
                rel_p = p.relative_to(target_dir).as_posix()
                if rel_p not in known_set or rel_p not in downloaded_files:
                    try:
                        p.unlink()
                        logger.info(f"Removed stale local file: repos/{repo_name}/{rel_p}")
                    except Exception as e:
                        logger.warning(f"Failed to remove stale file {rel_p}: {e}")

    if failed_required:
        logger.error(f"Sync failed for '{repo_name}': missing required files {failed_required}")
        return False

    logger.info(f"Successfully synced {len(downloaded_files)} context files into repos/{repo_name}")
    return True


def sync_all_subtrees():
    os.chdir(bot_root)
    repos_dir = bot_root / "repos"
    repos_dir.mkdir(exist_ok=True)

    success_count = 0
    total_count = len(REPO_METADATA)

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for repo_name, meta in REPO_METADATA.items():
            if sync_repo_context(repo_name, meta, client):
                success_count += 1

    logger.info(f"Subtree sync completed: {success_count}/{total_count} repositories synced successfully.")


if __name__ == "__main__":
    sync_all_subtrees()
