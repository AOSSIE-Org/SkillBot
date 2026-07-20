import sys
from pathlib import Path

bot_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(bot_root))

from repo_router import get_available_repos, load_repo_context, detect_repo_by_keywords

def test_routing():
    print("--- 1. Available Repositories ---")
    repos = get_available_repos()
    print("Discovered repos:", repos)

    print("\n--- 2. Keyword Detection Test ---")
    test_queries = [
        "How do I setup social share button?",
        "Where is the starter template?",
        "How to use pull request dashboard?",
    ]
    for q in test_queries:
        detected = detect_repo_by_keywords(q, repos)
        print(f"Query: '{q}' -> Detected: {detected}")

    print("\n--- 3. Repository Context Loading Test ---")
    for repo in repos:
        ctx = load_repo_context(repo)
        print(f"Repo: {repo} | Context length: {len(ctx)} chars")
        if ctx:
            first_lines = "\n".join(ctx.splitlines()[:10])
            print(f"Context snippet:\n{first_lines}\n")

if __name__ == "__main__":
    test_routing()
