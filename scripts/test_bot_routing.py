import asyncio
import sys
import io
from pathlib import Path

# Ensure UTF-8 output in Windows terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

bot_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(bot_root))

from repo_router import get_available_repos, load_repo_context, detect_repo_by_keywords, get_repo_from_thread_name
from bot import generate_ollama_response, load_skill_context

async def test_all():
    print("--- 1. Available Repositories ---")
    repos = get_available_repos()
    print("Discovered repos:", repos)

    print("\n--- 2. Thread Name Matching Test ---")
    thread_names = [
        "Social Share Button",
        "social-share-button",
        "Org Explorer",
        "Template Repo",
    ]
    for t_name in thread_names:
        mapped = get_repo_from_thread_name(t_name, repos)
        print(f"Thread Name: '{t_name}' -> Mapped Repo: {mapped}")

    print("\n--- 3. Keyword Detection Test ---")
    test_queries = [
        "what is this social-share-button do?",
        "How do I setup social share button?",
        "Where is the starter template?",
        "How to write my GSoC proposal?",
        "Check my proposal draft for AOSSIE",
    ]
    for q in test_queries:
        detected = detect_repo_by_keywords(q, repos)
        print(f"Query: '{q}' -> Detected: {detected}")

    print("\n--- 4. Dynamic Query Context Loading Test ---")
    intents = [
        ("Who is the maintainer of SocialShareButton?", "SocialShareButton"),
        ("How do I install dependencies and setup SocialShareButton?", "SocialShareButton"),
        ("What is the architecture and design of SocialShareButton?", "SocialShareButton"),
        ("How do I write a GSoC proposal for AOSSIE?", "GSoC-Proposal-Assistant"),
    ]
    for query_str, target_repo in intents:
        ctx = load_repo_context(target_repo, query_str)
        print(f"Query: '{query_str}' -> Loaded context length: {len(ctx)} chars")

    print("\n--- 5. End-to-End Response Generation Test ---")
    sample_repo = "SocialShareButton"
    sample_query = "How do I install dependencies for SocialShareButton?"
    repo_context = load_repo_context(sample_repo, sample_query)

    print(f"Target Repo: {sample_repo}")
    print(f"User Query: '{sample_query}'")
    print("Sending request to Ollama...")

    response, fallback = await generate_ollama_response(sample_query, repo_context)
    print(f"\nOllama Response (fallback={fallback}):\n")
    print(response)

    print("\n--- 6. Unrouted Query Fallback Test ---")
    unrouted_query = "Tell me a joke about bananas"
    skill_context = load_skill_context()
    fallback_prompt = (
        f"The user asked: '{unrouted_query}'. "
        f"No specific repository was matched from available projects ({', '.join(repos)}). "
        f"Politely ask the user which project they need help with or clarify their request."
    )
    fallback_response, _ = await generate_ollama_response(fallback_prompt, skill_context)
    print(f"Unrouted Query: '{unrouted_query}'")
    print(f"Bot Guardrail Clarification Response:\n{fallback_response}")

if __name__ == "__main__":
    asyncio.run(test_all())
