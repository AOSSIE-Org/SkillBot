import os
import sys
import subprocess
import logging
from pathlib import Path

# Add parent directory to sys.path to import repo_metadata
script_dir = Path(__file__).resolve().parent
bot_root = script_dir.parent
sys.path.insert(0, str(bot_root))

from repo_metadata import REPO_METADATA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("subtree-sync")


def run_command(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a shell command and return returncode and output."""
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Command failed with code {result.returncode}:\n{result.stderr}")
    else:
        logger.info(result.stdout.strip())
    return result.returncode, result.stdout + result.stderr


def get_head_commit() -> str:
    """Get the current HEAD commit hash."""
    code, out = run_command(["git", "rev-parse", "HEAD"], bot_root)
    return out.strip() if code == 0 else ""


def has_context_changes(old_commit: str, new_commit: str, prefix: str) -> bool:
    """Check if AGENTS.md or .agent/ in prefix has non-zero line changes between commits."""
    cmd = [
        "git",
        "diff",
        "--numstat",
        old_commit,
        new_commit,
        "--",
        f"{prefix}/AGENTS.md",
        f"{prefix}/.agent",
    ]
    code, out = run_command(cmd, bot_root)
    if code != 0 or not out.strip():
        return False

    total_changes = 0
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                added = int(parts[0]) if parts[0] != "-" else 0
                deleted = int(parts[1]) if parts[1] != "-" else 0
                total_changes += (added + deleted)
            except ValueError:
                pass
    return total_changes > 0


def sync_subtrees():
    os.chdir(bot_root)
    repos_dir = bot_root / "repos"
    repos_dir.mkdir(exist_ok=True)

    for repo_name, meta in REPO_METADATA.items():
        url = meta.get("url")
        if not url:
            logger.warning(f"No URL defined for {repo_name}, skipping.")
            continue

        git_url = url if url.endswith(".git") else f"{url}.git"
        prefix = f"repos/{repo_name}"
        prefix_path = bot_root / prefix
        is_new_subtree = not (prefix_path.exists() and any(prefix_path.iterdir()))

        if not is_new_subtree:
            logger.info(f"Subtree '{prefix}' exists. Pulling updates from {git_url}...")
            cmd = [
                "git",
                "subtree",
                "pull",
                f"--prefix={prefix}",
                git_url,
                "main",
                "--squash",
                "-m",
                f"sync: update {repo_name} subtree",
            ]
        else:
            logger.info(f"Subtree '{prefix}' does not exist. Adding subtree from {git_url}...")
            cmd = [
                "git",
                "subtree",
                "add",
                f"--prefix={prefix}",
                git_url,
                "main",
                "--squash",
                "-m",
                f"sync: add {repo_name} subtree",
            ]

        old_head = get_head_commit()
        code, out = run_command(cmd, bot_root)
        if code == 0:
            new_head = get_head_commit()
            if old_head and new_head and old_head != new_head:
                if is_new_subtree:
                    logger.info(f"Subtree '{prefix}' newly added. Keeping initial commit.")
                else:
                    if not has_context_changes(old_head, new_head, prefix):
                        logger.info(
                            f"No non-zero line changes in AGENTS.md or .agent/ for {repo_name}. Resetting commit."
                        )
                        run_command(["git", "reset", "--hard", old_head], bot_root)
                    else:
                        logger.info(
                            f"Non-zero line changes confirmed in AGENTS.md or .agent/ for {repo_name}. Keeping commit."
                        )
        else:
            logger.error(f"Failed to sync subtree for {repo_name}")


if __name__ == "__main__":
    sync_subtrees()
