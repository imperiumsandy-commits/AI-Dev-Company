import tempfile
import unittest
from pathlib import Path

from ai_dev_company.memory_store import MemoryStore


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
        self.assertTrue(any(item["title"] == "Persistent decision" for item in memories))

    def test_tasks_and_valid_state_transitions_persist(self):
        task = self.store.add_task(
            title="Build active memory",
            agent_id="business-analyst-pm",
            acceptance_criteria=["Memory survives restart", "Tests pass"],
        )
        queued = self.store.update_task(task["task_id"], status="queued")
        running = self.store.update_task(task["task_id"], status="running")
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(running["status"], "running")

        reopened = MemoryStore(root=self.root)
        tasks = reopened.list_tasks(agent_id="business-analyst-pm")
        self.assertEqual(tasks[0]["task_id"], task["task_id"])
        self.assertEqual(tasks[0]["status"], "running")

    def test_invalid_state_transition_is_rejected(self):
        task = self.store.add_task(title="Transition guard")
        with self.assertRaises(ValueError):
            self.store.update_task(task["task_id"], status="done")

    def test_checkpoint_and_events_are_saved(self):
        self.store.add_memory(
            scope="business-analyst-pm",
            kind="lesson",
            title="Planning lesson",
            content="Record acceptance criteria.",
        )
        checkpoint = self.store.save_checkpoint("test-checkpoint", "Unit test snapshot")
        self.assertGreater(checkpoint["checkpoint_id"], 0)

        reopened = MemoryStore(root=self.root)
        latest = reopened.latest_checkpoint()
        self.assertEqual(latest["name"], "test-checkpoint")
        events = reopened.list_events(limit=20)
        self.assertTrue(any(event["event_type"] == "checkpoint_saved" for event in events))

    def test_agent_memory_scope_is_validated(self):
        with self.assertRaises(ValueError):
            self.store.add_memory(
                scope="generic-agent", kind="note",
                title="Bad scope", content="Not one of our eight agents."
            )


if __name__ == "__main__":
    unittest.main()
