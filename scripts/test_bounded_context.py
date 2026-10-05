"""
Unit and smoke tests for bounded Markdown context loading in load_repo_context
(addresses AOSSIE-Org/SkillBot#24).

Follows the same convention as scripts/test_link_and_issue_features.py:
can be run directly with python:
    python scripts/test_bounded_context.py
or with pytest:
    pytest scripts/test_bounded_context.py
"""

import io
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

bot_root = Path(__file__).resolve().parent.parent
if str(bot_root) not in sys.path:
    sys.path.insert(0, str(bot_root))

import repo_router as rr

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


def section_1_read_capped_file():
    print("\n--- 1. Capped file read helper (_read_capped_file) ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        short_file = tmp_path / "short.md"
        short_file.write_text("Small content within limit", encoding="utf-8")

        res_short = rr._read_capped_file(short_file, max_chars=100)
        check("short file content intact", res_short == "Small content within limit")
        check("no truncation marker on short file", rr.TRUNCATION_MARKER not in res_short)

        large_file = tmp_path / "large.md"
        large_file.write_text("X" * 500, encoding="utf-8")

        res_large = rr._read_capped_file(large_file, max_chars=100)
        check("large file truncated to max_chars prefix", res_large.startswith("X" * 100))
        check("truncation marker appended", res_large.endswith(rr.TRUNCATION_MARKER))
        check("length equals cap + marker length", len(res_large) == 100 + len(rr.TRUNCATION_MARKER))


def section_2_append_bounded_section():
    print("\n--- 2. Section budget enforcement (_append_bounded_section) ---")
    parts = ["=== REPOSITORY: TestRepo ==="]
    success = rr._append_bounded_section(
        parts,
        "--- Header ---",
        "Short content",
        max_total_chars=1000,
    )
    check("section fits returns True", success is True)
    check("section added to parts", len(parts) == 2)
    check("joined text includes header and content", "--- Header ---\nShort content" in "\n\n".join(parts))

    # Partial fit where content is truncated to respect budget
    initial_len = len(parts[0]) + len("\n\n") + len(parts[1])
    budget = initial_len + 40
    partial_success = rr._append_bounded_section(
        parts,
        "--- Second ---",
        "Z" * 200,
        max_total_chars=budget,
    )
    check("overflowing section returns False", partial_success is False)
    joined = "\n\n".join(parts)
    check("assembled length stays within budget", len(joined) <= budget)
    check("truncation marker in assembled text", rr.TRUNCATION_MARKER in joined)

    # Exhausted budget rejects further additions
    exhausted_success = rr._append_bounded_section(
        parts,
        "--- Third ---",
        "Will not fit",
        max_total_chars=budget,
    )
    check("exhausted budget returns False", exhausted_success is False)
    check("no parts added when budget exhausted", len(parts) == 3)


def section_3_load_repo_context_mock():
    print("\n--- 3. load_repo_context bounds on mock repository ---")
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir) / "MockRepo"
        agent_dir = repo_dir / ".agent"
        (agent_dir / "info").mkdir(parents=True)
        (agent_dir / "core").mkdir(parents=True)
        (agent_dir / "instructions").mkdir(parents=True)

        (agent_dir / "info" / "operational-data.md").write_text("OPS_" + "O" * 4000, encoding="utf-8")
        (agent_dir / "core" / "architecture.md").write_text("ARCH_" + "A" * 4000, encoding="utf-8")
        (agent_dir / "instructions" / "setup.md").write_text("SETUP_" + "S" * 4000, encoding="utf-8")
        (repo_dir / "README.md").write_text("README_" + "R" * 4000, encoding="utf-8")

        orig_get_repo_path = rr.get_repo_path
        rr.get_repo_path = lambda name: repo_dir if name == "MockRepo" else orig_get_repo_path(name)
        try:
            ctx = rr.load_repo_context("MockRepo", "setup", max_file_chars=150, max_total_chars=1200)
            check("context total length strictly <= 1200", len(ctx) <= 1200)
            check("repository header present", "=== REPOSITORY: MockRepo ===" in ctx)
            check("operational data section present", "--- Operational Data" in ctx)
            check("architecture section present", "--- Core Architecture" in ctx)
            check("truncation marker present", rr.TRUNCATION_MARKER in ctx)

            # Check individual section lengths
            sections = ctx.split("\n\n")
            for section in sections:
                lines = section.split("\n", 1)
                if len(lines) == 2 and lines[0].startswith("---"):
                    body = lines[1]
                    if rr.TRUNCATION_MARKER in body:
                        before_marker = body.split(rr.TRUNCATION_MARKER)[0]
                        check("file content capped at max_file_chars", len(before_marker) <= 150)
                        break

            # Very small total budget
            ctx_tiny = rr.load_repo_context("MockRepo", "setup", max_file_chars=500, max_total_chars=250)
            check("tiny budget context <= 250", len(ctx_tiny) <= 250)
        finally:
            rr.get_repo_path = orig_get_repo_path


def section_4_load_repo_context_real_repo():
    print("\n--- 4. Real repository context loading with defaults ---")
    ctx = rr.load_repo_context("SocialShareButton", "How do I setup social share button?")
    check("real repo context <= DEFAULT_MAX_TOTAL_CONTEXT_CHARS", len(ctx) <= rr.DEFAULT_MAX_TOTAL_CONTEXT_CHARS)
    check("SocialShareButton header present", "=== REPOSITORY: SocialShareButton ===" in ctx)
    check("operational data or architecture loaded", ("--- Operational Data" in ctx) or ("--- Core Architecture" in ctx))


# Pytest adapters
def test_read_capped_file():
    section_1_read_capped_file()
    assert FAILED == 0


def test_append_bounded_section():
    section_2_append_bounded_section()
    assert FAILED == 0


def test_load_repo_context_mock():
    section_3_load_repo_context_mock()
    assert FAILED == 0


def test_load_repo_context_real_repo():
    section_4_load_repo_context_real_repo()
    assert FAILED == 0


def run_all():
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0
    section_1_read_capped_file()
    section_2_append_bounded_section()
    section_3_load_repo_context_mock()
    section_4_load_repo_context_real_repo()
    print(f"\n=== {PASSED} passed, {FAILED} failed ===")
    return FAILED == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
