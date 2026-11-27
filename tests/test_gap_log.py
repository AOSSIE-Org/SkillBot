"""Regression tests for gap-log persistence."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot


class GapLogPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """Verify failed gap-log saves cannot destroy previously saved entries."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.gap_log_path = Path(self.temp_dir.name) / "gap_log.json"
        self.original_path = bot.GAP_LOG_PATH
        self.original_lock = bot.gap_log_lock
        bot.GAP_LOG_PATH = self.gap_log_path
        bot.gap_log_lock = asyncio.Lock()

    def tearDown(self) -> None:
        bot.GAP_LOG_PATH = self.original_path
        bot.gap_log_lock = self.original_lock
        self.temp_dir.cleanup()

    def read_entries(self) -> list[dict]:
        with self.gap_log_path.open(encoding="utf-8") as log_file:
            return json.load(log_file)

    def temporary_files(self) -> list[Path]:
        return list(self.gap_log_path.parent.glob(".gap_log.json.*.tmp"))

    def test_save_writes_valid_json(self) -> None:
        entries = [{"query": "How do I install?", "reason": "no_matching_docs"}]

        bot._save_gap_log(entries)

        self.assertEqual(self.read_entries(), entries)

    async def test_log_gap_preserves_existing_records(self) -> None:
        existing_entry = {"query": "existing question", "reason": "unmapped_query"}
        bot._save_gap_log([existing_entry])

        await bot._log_gap("new question", "no_matching_docs", thread_id=42)

        entries = self.read_entries()
        self.assertEqual(entries[0], existing_entry)
        self.assertEqual(entries[1]["query"], "new question")
        self.assertEqual(entries[1]["reason"], "no_matching_docs")
        self.assertEqual(entries[1]["thread_id"], 42)

    def test_unserializable_entry_preserves_existing_log(self) -> None:
        existing_entries = [{"query": "existing question", "reason": "unmapped_query"}]
        bot._save_gap_log(existing_entries)

        class UnserializableEntry:
            def __str__(self) -> str:
                raise TypeError("not serializable")

        with self.assertRaisesRegex(TypeError, "not serializable"):
            bot._save_gap_log([UnserializableEntry()])

        self.assertEqual(self.read_entries(), existing_entries)
        self.assertEqual(self.temporary_files(), [])

    def test_replace_failure_preserves_existing_log_and_cleans_temp_file(self) -> None:
        existing_entries = [{"query": "existing question", "reason": "unmapped_query"}]
        bot._save_gap_log(existing_entries)

        with patch("bot.os.replace", side_effect=OSError("replace interrupted")):
            with self.assertRaisesRegex(OSError, "replace interrupted"):
                bot._save_gap_log([{"query": "new question", "reason": "no_matching_docs"}])

        self.assertEqual(self.read_entries(), existing_entries)
        self.assertEqual(self.temporary_files(), [])

    async def test_concurrent_gap_writes_keep_every_entry(self) -> None:
        queries = [f"question {number}" for number in range(20)]

        await asyncio.gather(*(bot._log_gap(query, "no_matching_docs") for query in queries))

        entries = self.read_entries()
        self.assertEqual(len(entries), len(queries))
        self.assertEqual({entry["query"] for entry in entries}, set(queries))


if __name__ == "__main__":
    unittest.main()
