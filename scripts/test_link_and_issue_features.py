"""
Edge-case smoke test for the domain-allowlisted external link fetching and the
explicit-request-only GitHub issue creation feature (added 2026-08-01).

Follows the same plain print-based convention as test_bot_routing.py / routing_smoke_check.py
(no pytest in this project) — run directly:

    venv/Scripts/python.exe scripts/test_link_and_issue_features.py

Sections 1, 3, 6, 7 are pure-function/mocked and safe to re-run anytime. Sections 2, 4, 5
make real (read-only) calls to api.github.com / api.stackexchange.com. Nothing in this file
ever calls create_github_issue against the real gh CLI — that path is mocked in section 8.
"""

import asyncio
import io
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

bot_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(bot_root))

import repo_router as rr
from bot import is_issue_creation_request, parse_issue_draft

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}  {('- ' + detail) if detail else ''}")


async def section_1_domain_allowlist():
    print("\n--- 1. Domain allowlist / SSRF safety (_is_allowed_domain) ---")
    check("exact match: stackoverflow.com", rr._is_allowed_domain("https://stackoverflow.com/questions/1"))
    check("subdomain: www.stackoverflow.com", rr._is_allowed_domain("https://www.stackoverflow.com/questions/1"))
    check("subdomain: es.stackoverflow.com", rr._is_allowed_domain("https://es.stackoverflow.com/questions/1"))
    check("case-insensitive host: STACKOVERFLOW.COM", rr._is_allowed_domain("https://STACKOVERFLOW.COM/questions/1"))
    check(
        "bypass attempt rejected: stackoverflow.com.evil.com",
        not rr._is_allowed_domain("https://stackoverflow.com.evil.com/questions/1"),
    )
    check(
        "bypass attempt rejected: evilstackoverflow.com (no dot)",
        not rr._is_allowed_domain("https://evilstackoverflow.com/questions/1"),
    )
    check(
        "userinfo bypass rejected: stackoverflow.com@evil.com",
        not rr._is_allowed_domain("https://stackoverflow.com@evil.com/"),
    )
    check("github.com NOT generic-allowed (handled separately)", not rr._is_allowed_domain("https://github.com/foo/bar"))
    check("random domain rejected: evil.com", not rr._is_allowed_domain("http://evil.com/"))
    check(
        "SSRF probe rejected: cloud metadata IP",
        not rr._is_allowed_domain("http://169.254.169.254/latest/meta-data/"),
    )
    check("SSRF probe rejected: localhost", not rr._is_allowed_domain("http://localhost:11434/"))
    check(
        "generic fetch never touches network for disallowed domain",
        await rr.fetch_generic_link_info("http://evil.com/") is None,
    )


async def section_2_github_link_fetch_live():
    print("\n--- 2. GitHub PR/Issue fetch — regex + case-insensitivity (live api.github.com) ---")
    check(
        "malformed URL returns None (no network)",
        await rr.fetch_github_link_info("https://github.com/AOSSIE-Org/Template-Repo") is None,
    )
    info = await rr.fetch_github_link_info("https://github.com/AOSSIE-Org/Template-Repo/pull/2")
    check("lowercase PR link fetches and labels as PR", bool(info) and "PR" in info, repr(info)[:120])

    info_mixed_case = await rr.fetch_github_link_info("https://GitHub.com/AOSSIE-Org/Template-Repo/Pull/2")
    check(
        "mixed-case github.com/Pull/ still recognized as a PR (not misfiled as Issue)",
        bool(info_mixed_case) and "PR" in info_mixed_case,
        repr(info_mixed_case)[:120],
    )


async def section_3_stackoverflow_edge_cases():
    print("\n--- 3. Stack Overflow fetch edge cases (live api.stackexchange.com) ---")
    check(
        "non-matching URL (no /questions/<id>) returns None",
        await rr.fetch_stackoverflow_info("https://stackoverflow.com/") is None,
    )

    no_slug = await rr.fetch_stackoverflow_info("https://stackoverflow.com/questions/231767")
    check("URL with no slug still extracts question ID", bool(no_slug) and "Q231767" in no_slug)

    with_query = await rr.fetch_stackoverflow_info(
        "https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python?rq=1"
    )
    check("URL with trailing query string still extracts question ID", bool(with_query) and "Q231767" in with_query)

    entity_decoded = await rr.fetch_stackoverflow_info(
        "https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python"
    )
    check(
        "HTML entities decoded in title (no raw &quot; leaking through)",
        bool(entity_decoded) and "&quot;" not in entity_decoded and '"yield"' in entity_decoded,
        repr(entity_decoded)[:150] if entity_decoded else "",
    )

    nonexistent = await rr.fetch_stackoverflow_info("https://stackoverflow.com/questions/999999999999999")
    check(
        "nonexistent question ID degrades to None, does not crash",
        nonexistent is None,
        repr(nonexistent),
    )


async def section_4_extract_and_fetch_integration():
    print("\n--- 4. extract_and_fetch_external_links integration (dedup, cap, mixed domains) ---")

    check("no URLs in text returns '' immediately", await rr.extract_and_fetch_external_links("just a plain question") == "")

    call_urls = []

    async def fake_github_fetch(url):
        call_urls.append(url)
        return f"--- Fetched GitHub PR Details ---\n{url}"

    dup_text = (
        "see https://github.com/AOSSIE-Org/Template-Repo/pull/2 "
        "and https://github.com/AOSSIE-Org/Template-Repo/pull/2/ "
        "and https://github.com/AOSSIE-Org/Template-Repo/pull/2 again"
    )
    with patch("repo_router.fetch_github_link_info", fake_github_fetch):
        await rr.extract_and_fetch_external_links(dup_text)
    check(
        "same URL (with/without trailing slash) deduped to 1 fetch",
        len(call_urls) == 1,
        f"got {len(call_urls)} calls: {call_urls}",
    )

    call_urls.clear()
    many_links_text = " ".join(
        f"https://github.com/AOSSIE-Org/Template-Repo/pull/{i}" for i in range(1, 9)
    )  # 8 distinct URLs
    with patch("repo_router.fetch_github_link_info", fake_github_fetch):
        await rr.extract_and_fetch_external_links(many_links_text)
    check(
        "MAX_LINKS cap respected across 8 distinct URLs (<=5 fetched)",
        len(call_urls) <= 5,
        f"got {len(call_urls)} calls",
    )

    mixed_text = (
        "check https://github.com/AOSSIE-Org/Template-Repo/pull/2 , "
        "https://stackoverflow.com/questions/231767/what-does-the-yield-keyword-do-in-python , "
        "and http://evil.com/ (should be silently dropped)"
    )
    combined = await rr.extract_and_fetch_external_links(mixed_text)
    check(
        "mixed message: GitHub + Stack Overflow both fetched, evil.com silently dropped",
        "Fetched GitHub PR" in combined and "Fetched Stack Overflow" in combined and "evil.com" not in combined,
        combined[:200],
    )


def section_5_issue_trigger_detection():
    print("\n--- 5. Issue-creation trigger detection (word-boundary, case-insensitive) ---")

    true_cases = [
        "can you create an issue for this",
        "please open an issue",
        "I'd like to file an issue about this bug",
        "raise an issue for this please",
        "make an issue for this bug",
        "CREATE AN ISSUE",
        "create a issue for this",  # grammatically odd but should still match ("an?")
    ]
    for q in true_cases:
        check(f"should trigger: {q!r}", is_issue_creation_request(q))

    false_cases = [
        "what issues are open",
        "any issues with this?",
        "this issue is annoying",
        "issue-tracker.md",
        "opened an issue yesterday",  # past tense "opened" must not match "open"
        "no issue here",
    ]
    for q in false_cases:
        check(f"should NOT trigger: {q!r}", not is_issue_creation_request(q))

    # Known limitation, documented rather than "fixed" — negation isn't detected by a
    # word-boundary regex. Recorded here so it's a visible, intentional gap, not a silent one.
    negation_query = "please don't create an issue for this"
    fires = is_issue_creation_request(negation_query)
    print(
        f"  INFO  known limitation: {negation_query!r} -> triggers={fires} "
        f"(negation isn't detected; regex only matches the phrase, not sentence polarity)"
    )


def section_6_parse_issue_draft():
    print("\n--- 6. parse_issue_draft edge cases ---")

    title, body = parse_issue_draft("TITLE: Fix crash\nBODY: It crashes when X happens.\nMore detail.")
    check("well-formed draft parses both fields", title == "Fix crash" and body == "It crashes when X happens.\nMore detail.")

    title2, body2 = parse_issue_draft("TITLE: Only a title, no body marker")
    check("missing BODY: -> body is None, title still parsed", title2 == "Only a title, no body marker" and body2 is None)

    title3, body3 = parse_issue_draft("BODY: only a body, no title marker")
    check("missing TITLE: -> title is None, body still parsed", title3 is None and body3 == "only a body, no title marker")

    title4, body4 = parse_issue_draft(
        "Sure, here you go:\nTITLE: Crash on startup\nBODY: Para one.\n\nPara two after a blank line."
    )
    check(
        "preamble before TITLE: doesn't break parsing; multi-paragraph BODY captured in full",
        title4 == "Crash on startup" and body4 == "Para one.\n\nPara two after a blank line.",
        repr((title4, body4)),
    )

    title5, body5 = parse_issue_draft("title: lowercase marker\nbody: also lowercase")
    check(
        "lowercase 'title:'/'body:' markers still parse (model doesn't always match case exactly)",
        title5 == "lowercase marker" and body5 == "also lowercase",
        repr((title5, body5)),
    )

    title6, body6 = parse_issue_draft("no markers at all here")
    check("no markers at all -> both None", title6 is None and body6 is None)


def section_7_get_repo_full_name():
    print("\n--- 7. get_repo_full_name edge cases ---")

    check(
        "plain url (no branch suffix): GSoC-Info-Assistant",
        rr.get_repo_full_name("GSoC-Info-Assistant") == "kpj2006/GSoC-Info-Assistant",
    )
    check(
        "url with /tree/<branch> suffix stripped: SocialShareButton",
        rr.get_repo_full_name("SocialShareButton") == "kpj2006/SocialShareButton",
    )
    check(
        "url with /tree/<branch> suffix stripped: OrgExplorer",
        rr.get_repo_full_name("OrgExplorer") == "kpj2006/OrgExplorer",
    )
    check(
        "unknown repo name (not in REPO_METADATA) -> None",
        rr.get_repo_full_name("Definitely-Not-A-Real-Repo-Name") is None,
    )


async def section_8_create_github_issue_mocked():
    print("\n--- 8. create_github_issue — mocked subprocess (no real gh calls, no real issues created) ---")

    success_proc = AsyncMock()
    success_proc.communicate.return_value = (b"https://github.com/kpj2006/Repo/issues/42\n", b"")
    success_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=success_proc)):
        url = await rr.create_github_issue("kpj2006/Repo", "Test title", "Test body")
    check("success path returns the created issue URL", url == "https://github.com/kpj2006/Repo/issues/42")

    fail_proc = AsyncMock()
    fail_proc.communicate.return_value = (b"", b"HTTP 403: Resource not accessible")
    fail_proc.returncode = 1
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fail_proc)):
        url2 = await rr.create_github_issue("kpj2006/Repo", "Test title", "Test body")
    check("non-zero exit code returns None (not a crash, not a fake URL)", url2 is None)

    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError())):
        url3 = await rr.create_github_issue("kpj2006/Repo", "Test title", "Test body")
    check("gh binary missing (FileNotFoundError) returns None gracefully", url3 is None)

    hang_proc = AsyncMock()
    hang_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    hang_proc.kill = lambda: None  # sync method on a real Process object
    hang_proc.wait = AsyncMock(return_value=0)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=hang_proc)):
        url4 = await rr.create_github_issue("kpj2006/Repo", "Test title", "Test body")
    check("hung gh process times out, gets killed, returns None (not left running)", url4 is None)
    check("timeout path awaited proc.wait() to reap the killed process", hang_proc.wait.called)


async def section_9_link_budget_and_redirect_revalidation():
    print("\n--- 9. Link-fetch budget (attempted, not successful) + redirect re-validation ---")

    async def always_fails(url):
        return None  # simulates every GitHub fetch failing (rate-limited, 404, network error, ...)

    generic_calls = []

    async def fake_generic_fetch(url):
        generic_calls.append(url)
        return f"--- Fetched Page: {url} ---\nstub"

    text = " ".join(
        [f"https://github.com/AOSSIE-Org/Template-Repo/pull/{i}" for i in range(1, 4)]  # 3 failing github URLs
        + [f"https://stackoverflow.com/questions/{i}" for i in range(1, 5)]  # 4 candidate generic URLs
    )
    with patch("repo_router.fetch_github_link_info", always_fails), \
         patch("repo_router.fetch_generic_link_info", fake_generic_fetch):
        await rr.extract_and_fetch_external_links(text)
    check(
        "budget charges 3 slots for 3 ATTEMPTED (failed) GitHub fetches, leaving exactly 2 for generic",
        len(generic_calls) == 2,
        f"got {len(generic_calls)} generic calls (old buggy behavior would allow 5, since 0 succeeded)",
    )

    class _FakeResponse:
        def __init__(self, url, status_code=200, text=""):
            self.url = url
            self.status_code = status_code
            self.text = text

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            # Simulate an allowlisted domain redirecting to a host that is NOT allowlisted.
            return _FakeResponse(url="http://evil.com/phished", status_code=200, text="<p>hi</p>")

    # NOTE: stackoverflow.com — the only domain in ALLOWED_EXTERNAL_DOMAINS today — is
    # special-cased straight to the api.stackexchange.com path and never reaches this generic
    # HTML-fetch branch at all, so the redirect-revalidation code being tested here is currently
    # unreachable in production. It only matters once a second, non-API domain is added to the
    # allowlist — temporarily add one here so the branch is actually exercised.
    with patch.object(rr, "ALLOWED_EXTERNAL_DOMAINS", {"example-docs.test"}), \
         patch("repo_router.httpx.AsyncClient", _FakeClient):
        result = await rr.fetch_generic_link_info("https://example-docs.test/some-redirecting-link")
    check(
        "final redirected URL re-validated against the allowlist — rejects if it lands outside it",
        result is None,
    )


async def main():
    await section_1_domain_allowlist()
    await section_2_github_link_fetch_live()
    await section_3_stackoverflow_edge_cases()
    await section_4_extract_and_fetch_integration()
    section_5_issue_trigger_detection()
    section_6_parse_issue_draft()
    section_7_get_repo_full_name()
    await section_8_create_github_issue_mocked()
    await section_9_link_budget_and_redirect_revalidation()

    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    if FAILED:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
