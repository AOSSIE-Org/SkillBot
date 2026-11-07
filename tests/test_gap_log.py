"""Tests for the gap-log writer in ``bot.py``.

Run with: ``python -m unittest discover -s tests``
"""

import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot  # noqa: E402  (import after sys.path setup)


class GapLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log_path = Path(tmp.name) / "gap_log.json"
        self._original_gap_log_path = bot.GAP_LOG_PATH
        self._original_lock = bot.gap_log_lock
        bot.GAP_LOG_PATH = self.log_path
        # An asyncio.Lock may bind to the loop that first uses it; give every
        # test a fresh lock so the module-level one is not reused across loops.
        bot.gap_log_lock = asyncio.Lock()
        self.addCleanup(self._restore_module_state)

    def _restore_module_state(self):
        bot.GAP_LOG_PATH = self._original_gap_log_path
        bot.gap_log_lock = self._original_lock

    def _read_log(self):
        return json.loads(self.log_path.read_text(encoding="utf-8"))

    async def test_appends_entry_and_keeps_existing_entries(self):
        self.log_path.write_text(
            json.dumps([{"query": "old", "reason": "seed"}]), encoding="utf-8"
        )

        await bot._log_gap("how do I install", "no_matching_docs", thread_id=42)

        entries = self._read_log()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["query"], "old")
        self.assertEqual(entries[1]["query"], "how do I install")
        self.assertEqual(entries[1]["reason"], "no_matching_docs")
        self.assertEqual(entries[1]["thread_id"], 42)
        self.assertIn("timestamp", entries[1])

    async def test_starts_fresh_when_log_is_corrupt(self):
        self.log_path.write_text("{not json", encoding="utf-8")

        await bot._log_gap("q", "no_matching_docs")

        entries = self._read_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["query"], "q")

    async def test_concurrent_writes_are_not_lost(self):
        await asyncio.gather(
            *(bot._log_gap(f"q{i}", "no_matching_docs") for i in range(25))
        )

        self.assertEqual(len(self._read_log()), 25)

    async def test_file_io_runs_off_the_event_loop_thread(self):
        """Regression test for #57: the sync read/write must not run inline."""
        loop_thread = threading.get_ident()
        io_threads = []
        real_load, real_save = bot._load_gap_log, bot._save_gap_log

        def load():
            io_threads.append(threading.get_ident())
            return real_load()

        def save(entries):
            io_threads.append(threading.get_ident())
            real_save(entries)

        with patch.object(bot, "_load_gap_log", load), patch.object(
            bot, "_save_gap_log", save
        ):
            await bot._log_gap("q", "no_matching_docs")

        self.assertEqual(len(io_threads), 2)
        self.assertNotIn(loop_thread, io_threads)


if __name__ == "__main__":
    unittest.main()
