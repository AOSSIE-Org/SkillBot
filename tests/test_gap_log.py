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


class SpyLock:
    """An asyncio.Lock that signals when a second caller reaches it."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._entered = 0
        self.second_attempt = asyncio.Event()

    async def __aenter__(self):
        self._entered += 1
        if self._entered >= 2:
            self.second_attempt.set()
        await self._lock.acquire()
        return self

    async def __aexit__(self, *_exc):
        self._lock.release()

    def locked(self):
        return self._lock.locked()


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

    async def test_starts_fresh_when_log_is_not_a_list(self):
        self.log_path.write_text(json.dumps({"query": "not a list"}), encoding="utf-8")

        await bot._log_gap("q", "no_matching_docs")

        entries = self._read_log()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["query"], "q")

    async def test_concurrent_writes_are_not_lost(self):
        await asyncio.gather(
            *(bot._log_gap(f"q{i}", "no_matching_docs") for i in range(25))
        )

        self.assertEqual(len(self._read_log()), 25)

    async def test_second_load_waits_for_first_save(self):
        """The lock must cover the whole read-modify-write sequence.

        The first save is held open in its worker thread. The second call
        must reach the lock before it loads; without the lock it loads
        mid-write, so this fails even when writes happen to run serially.
        """
        events = []
        save_started = threading.Event()
        release_save = threading.Event()
        second_load_seen = threading.Event()
        real_load, real_save = bot._load_gap_log, bot._save_gap_log

        def tracking_load():
            events.append("load")
            if events.count("load") >= 2:
                second_load_seen.set()
            return real_load()

        def blocking_save(entries):
            events.append("save_start")
            save_started.set()
            if not release_save.wait(timeout=10):
                raise TimeoutError("test never released the first save")
            real_save(entries)
            events.append("save_end")

        spy = SpyLock()
        bot.gap_log_lock = spy
        with patch.object(bot, "_load_gap_log", tracking_load), patch.object(
            bot, "_save_gap_log", blocking_save
        ):
            first = asyncio.create_task(bot._log_gap("first", "no_matching_docs"))
            self.assertTrue(await asyncio.to_thread(save_started.wait, 10))
            second = asyncio.create_task(bot._log_gap("second", "no_matching_docs"))
            at_lock = asyncio.create_task(spy.second_attempt.wait())
            load_ran = asyncio.create_task(asyncio.to_thread(second_load_seen.wait, 10))
            try:
                done, _ = await asyncio.wait(
                    {at_lock, load_ran}, timeout=10, return_when=asyncio.FIRST_COMPLETED
                )
                # Reaching the lock is fine; running the second load is not.
                self.assertIn(at_lock, done, "the second call never reached the lock")
                self.assertNotIn(load_ran, done, "the second call loaded before the save finished")
            finally:
                release_save.set()
                at_lock.cancel()
                load_ran.cancel()
            await asyncio.gather(first, second)

        self.assertEqual(len(self._read_log()), 2)
        # The second load must come after the first save finished.
        self.assertGreater(events.index("load", 1), events.index("save_end"))

    async def test_cancelled_caller_keeps_lock_until_save_finishes(self):
        """Cancelling a caller mid-save must not release the lock early.

        ``asyncio.to_thread`` cannot stop the worker thread, so a cancelled
        caller must still wait for the write before releasing the lock —
        otherwise the next caller can read a partially written log.
        """
        save_started = threading.Event()
        release_save = threading.Event()
        real_save = bot._save_gap_log

        def blocking_save(entries):
            save_started.set()
            if not release_save.wait(timeout=10):
                raise TimeoutError("test never released the save")
            real_save(entries)

        with patch.object(bot, "_save_gap_log", blocking_save):
            caller = asyncio.create_task(bot._log_gap("q", "no_matching_docs"))
            self.assertTrue(await asyncio.to_thread(save_started.wait, 10))
            caller.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            # The worker is still writing: the lock must still be held.
            self.assertTrue(bot.gap_log_lock.locked())
            release_save.set()
            with self.assertRaises(asyncio.CancelledError):
                await caller

        self.assertFalse(bot.gap_log_lock.locked())
        self.assertEqual(len(self._read_log()), 1)

    async def test_repeated_cancellation_still_waits_for_the_save(self):
        """A second cancellation must not release the lock mid-write."""
        save_started = threading.Event()
        release_save = threading.Event()
        real_save = bot._save_gap_log

        def blocking_save(entries):
            save_started.set()
            if not release_save.wait(timeout=10):
                raise TimeoutError("test never released the save")
            real_save(entries)

        with patch.object(bot, "_save_gap_log", blocking_save):
            caller = asyncio.create_task(bot._log_gap("q", "no_matching_docs"))
            self.assertTrue(await asyncio.to_thread(save_started.wait, 10))
            caller.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            # Now waiting out the save; cancel again while it waits.
            caller.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertTrue(bot.gap_log_lock.locked())
            release_save.set()
            with self.assertRaises(asyncio.CancelledError):
                await caller

        self.assertFalse(bot.gap_log_lock.locked())
        self.assertEqual(len(self._read_log()), 1)

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
