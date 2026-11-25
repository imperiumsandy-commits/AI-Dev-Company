import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from ai_dev_company.memory_store import MemoryStore, SEED_MEMORIES


class ActiveMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = MemoryStore(root=self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bootstrap_seeds_project_vision(self):
        memories = self.store.list_memories(scope="project", limit=100)
        titles = {item["title"] for item in memories}

        self.assertIn("Eight independent specialist developers", titles)
        self.assertIn("Quality before completion", titles)

    def test_memory_survives_new_runtime_instance(self):
        self.store.add_memory(
            scope="project",
            kind="decision",
            title="Persistent decision",
            content="Keep specialist logic independent.",
        )

        reopened = MemoryStore(root=self.root)
        memories = reopened.list_memories(scope="project", limit=100)

        self.assertTrue(
            any(item["title"] == "Persistent decision" for item in memories)
        )

    def test_tasks_and_valid_state_transitions_persist(self):
        task = self.store.add_task(
            title="Build active memory",
            agent_id="business-analyst-pm",
            acceptance_criteria=[
                "Memory survives restart",
                "Tests pass",
            ],
        )

        queued = self.store.update_task(
            task["task_id"],
            status="queued",
        )
        running = self.store.update_task(
            task["task_id"],
            status="running",
        )

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(running["status"], "running")

        reopened = MemoryStore(root=self.root)
        tasks = reopened.list_tasks(agent_id="business-analyst-pm")

        self.assertEqual(tasks[0]["task_id"], task["task_id"])
        self.assertEqual(tasks[0]["status"], "running")

    def test_invalid_state_transition_is_rejected(self):
        task = self.store.add_task(title="Transition guard")

        with self.assertRaises(ValueError):
            self.store.update_task(
                task["task_id"],
                status="done",
            )

    def test_checkpoint_and_events_are_saved(self):
        self.store.add_memory(
            scope="business-analyst-pm",
            kind="lesson",
            title="Planning lesson",
            content="Record acceptance criteria.",
        )

        checkpoint = self.store.save_checkpoint(
            "test-checkpoint",
            "Unit test snapshot",
        )

        self.assertGreater(checkpoint["checkpoint_id"], 0)

        reopened = MemoryStore(root=self.root)
        latest = reopened.latest_checkpoint()

        self.assertEqual(latest["name"], "test-checkpoint")

        events = reopened.list_events(limit=20)

        self.assertTrue(
            any(
                event["event_type"] == "checkpoint_saved"
                for event in events
            )
        )

    def test_agent_memory_scope_is_validated(self):
        with self.assertRaises(ValueError):
            self.store.add_memory(
                scope="generic-agent",
                kind="note",
                title="Bad scope",
                content="Not one of our eight agents.",
            )

    def test_concurrent_first_start_seeds_memory_only_once(self):
        concurrent_root = self.root / "concurrent-first-start"
        concurrent_root.mkdir()

        workers = 4
        start_barrier = Barrier(workers)

        def initialize_store(_):
            start_barrier.wait(timeout=10)
            return MemoryStore(root=concurrent_root)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            stores = list(
                executor.map(initialize_store, range(workers))
            )

        memories = stores[0].list_memories(
            scope="project",
            limit=100,
        )

        titles = [item["title"] for item in memories]

        for _, _, expected_title, _ in SEED_MEMORIES:
            self.assertEqual(
                titles.count(expected_title),
                1,
                msg=f"Seed memory duplicated or missing: {expected_title}",
            )

        events = stores[0].list_events(limit=100)

        bootstrap_events = [
            event for event in events
            if event["event_type"] == "memory_bootstrapped"
        ]

        self.assertEqual(len(bootstrap_events), 1)

    def test_concurrent_task_transitions_preserve_event_order(self):
        task = self.store.add_task(
            title="Concurrent task transition",
        )

        start_barrier = Barrier(2)

        def transition(target_status):
            start_barrier.wait(timeout=10)

            return self.store.update_task(
                task["task_id"],
                status=target_status,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            queued_future = executor.submit(
                transition,
                "queued",
            )
            blocked_future = executor.submit(
                transition,
                "blocked",
            )

            queued_future.result(timeout=20)
            blocked_future.result(timeout=20)

        events = self.store.list_events(limit=200)

        task_updates = sorted(
            [
                event for event in events
                if event["event_type"] == "task_updated"
                and event["entity_id"] == task["task_id"]
            ],
            key=lambda event: event["event_id"],
        )

        self.assertEqual(len(task_updates), 2)

        first = task_updates[0]["payload"]
        second = task_updates[1]["payload"]

        self.assertEqual(first["old_status"], "planned")
        self.assertIn(first["new_status"], {"queued", "blocked"})

        self.assertEqual(
            second["old_status"],
            first["new_status"],
        )

        self.assertIn(second["new_status"], {"queued", "blocked"})

        self.assertEqual(
            self.store.list_tasks(limit=100)[0]["status"],
            second["new_status"],
        )

    def test_checkpoint_summary_uses_same_write_transaction(self):
        self.store.add_memory(
            scope="project",
            kind="decision",
            title="Checkpoint consistency decision",
            content="The saved checkpoint must contain this decision.",
        )

        original_summary = self.store._summary_from_connection
        transaction_states = []

        def observe_summary(connection):
            transaction_states.append(connection.in_transaction)
            return original_summary(connection)

        self.store._summary_from_connection = observe_summary

        self.store.save_checkpoint(
            "consistent-checkpoint",
            "Verify transactional summary",
        )

        self.assertEqual(transaction_states, [True])

        latest = self.store.latest_checkpoint()
        snapshot = latest["payload"]["project_summary"]

        self.assertTrue(
            any(
                item["title"] == "Checkpoint consistency decision"
                for item in snapshot["recent_memories"]
            )
        )


if __name__ == "__main__":
    unittest.main()
