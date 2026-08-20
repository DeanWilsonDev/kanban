import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "kanban.py"


def run(root, *args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


class KanbanCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "docs" / "kanban"

    def tearDown(self):
        self._tmp.cleanup()

    def test_init_creates_root_index(self):
        rc, out, err = run(self.root, "init")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.root / "_index.csv").exists())

    def test_new_epic_feature_story_task_chain(self):
        run(self.root, "init")
        rc, out, err = run(self.root, "new", "epic", "Nyx Native App", "--priority", "1")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.root / "nyx-native-app" / "epic.json").exists())

        rc, out, err = run(self.root, "new", "feature", "nyx-native-app", "Phase 2", "--priority", "1")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.root / "nyx-native-app" / "phase-2" / "feature.json").exists())

        rc, out, err = run(self.root, "new", "story", "nyx-native-app/phase-2", "2e NativeNodeRef", "--priority", "1")
        self.assertEqual(rc, 0, err)
        story_dir = self.root / "nyx-native-app" / "phase-2" / "2e-nativenoderef"
        self.assertTrue((story_dir / "story.json").exists())

        rc, out, err = run(self.root, "new", "task", "nyx-native-app/phase-2/2e-nativenoderef",
                            "Convert to BuildTreeRow", "--priority", "2")
        self.assertEqual(rc, 0, err)
        self.assertTrue((story_dir / "convert-to-buildtreerow.json").exists())

    def test_task_can_attach_directly_to_epic_or_feature(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Visual Test Flakiness", "--priority", "2")
        rc, out, err = run(self.root, "new", "task", "visual-test-flakiness", "Verify on Linux", "--priority", "2")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.root / "visual-test-flakiness" / "verify-on-linux.json").exists())

        run(self.root, "new", "feature", "visual-test-flakiness", "Follow-up", "--priority", "3")
        rc, out, err = run(self.root, "new", "task", "visual-test-flakiness/follow-up", "Sub task", "--priority", "3")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.root / "visual-test-flakiness" / "follow-up" / "sub-task.json").exists())

    def test_story_cannot_have_feature_child(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "feature", "epic", "Feature", "--priority", "1")
        run(self.root, "new", "story", "epic/feature", "Story", "--priority", "1")
        rc, out, err = run(self.root, "new", "feature", "epic/feature/story", "Nope", "--priority", "1")
        self.assertNotEqual(rc, 0)
        self.assertIn("cannot have a feature child", err)

    def test_status_and_priority_update_in_place(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "3")
        run(self.root, "new", "task", "epic", "Task B", "--priority", "3")

        rc, out, err = run(self.root, "status", "epic/task-a", "in-progress")
        self.assertEqual(rc, 0, err)
        rc, out, err = run(self.root, "priority", "epic/task-a", "1")
        self.assertEqual(rc, 0, err)

        rc, out, err = run(self.root, "list", "epic")
        self.assertEqual(rc, 0, err)
        self.assertIn("in-progress", out)
        # task-b untouched
        rc, out, err = run(self.root, "show", "epic/task-b")
        self.assertIn("priority=3", out)
        self.assertIn("status=todo", out)

    def test_next_sorts_by_priority_then_created(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Low prio", "--priority", "5")
        run(self.root, "new", "task", "epic", "High prio", "--priority", "1")
        run(self.root, "new", "task", "epic", "Mid prio", "--priority", "3")

        rc, out, err = run(self.root, "next", "--top", "10")
        self.assertEqual(rc, 0, err)
        lines = [l for l in out.strip().splitlines()]
        self.assertTrue(lines[0].startswith("1 "))
        self.assertIn("high-prio", lines[0])
        self.assertTrue(lines[-1].startswith("5 "))

    def test_in_progress_finds_any_tier(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "feature", "epic", "Feature", "--priority", "1")
        run(self.root, "status", "epic/feature", "in-progress")

        rc, out, err = run(self.root, "in-progress")
        self.assertEqual(rc, 0, err)
        self.assertIn("feature", out)

    def test_lint_clean_on_fresh_tree(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "1")
        rc, out, err = run(self.root, "lint")
        self.assertEqual(rc, 0, err)
        self.assertIn("clean", out)

    def test_lint_catches_broken_reference(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "1")
        (self.root / "epic" / "task-a.json").unlink()

        rc, out, err = run(self.root, "lint")
        self.assertNotEqual(rc, 0)
        self.assertIn("does not exist", out)

    def test_lint_catches_orphan_file(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        (self.root / "epic" / "mystery.json").write_text("# stray\n")

        rc, out, err = run(self.root, "lint")
        self.assertNotEqual(rc, 0)
        self.assertIn("orphan", out)

    def test_invalid_priority_rejected(self):
        run(self.root, "init")
        rc, out, err = run(self.root, "new", "epic", "Epic", "--priority", "9")
        self.assertNotEqual(rc, 0)
        self.assertIn("1-5", err)

    def test_item_json_is_self_contained(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Nyx Native App", "--priority", "1")
        run(self.root, "new", "task", "nyx-native-app", "Do the thing", "--priority", "2")

        record = json.loads((self.root / "nyx-native-app" / "do-the-thing.json").read_text())
        self.assertEqual(record["id"], "do-the-thing")
        self.assertEqual(record["path"], "nyx-native-app/do-the-thing")
        self.assertEqual(record["kind"], "task")
        self.assertEqual(record["name"], "Do the thing")
        self.assertEqual(record["status"], "todo")
        self.assertEqual(record["priority"], 2)
        self.assertEqual(record["parent"], "nyx-native-app")
        self.assertIn("created", record)
        self.assertIn("updated", record)
        self.assertEqual(record["body"], "")

        epic_record = json.loads((self.root / "nyx-native-app" / "epic.json").read_text())
        self.assertIsNone(epic_record["parent"])
        self.assertEqual(epic_record["path"], "nyx-native-app")

    def test_status_and_priority_update_mirror_into_json(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "3")

        run(self.root, "status", "epic/task-a", "in-progress")
        run(self.root, "priority", "epic/task-a", "1")

        record = json.loads((self.root / "epic" / "task-a.json").read_text())
        self.assertEqual(record["status"], "in-progress")
        self.assertEqual(record["priority"], 1)

    def test_body_command_replaces_body_from_file(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "1")

        body_file = Path(self._tmp.name) / "body.txt"
        body_file.write_text("Root cause: X. Fixed via commit abc123.\n")
        rc, out, err = run(self.root, "body", "epic/task-a", "--file", str(body_file))
        self.assertEqual(rc, 0, err)

        record = json.loads((self.root / "epic" / "task-a.json").read_text())
        self.assertEqual(record["body"], "Root cause: X. Fixed via commit abc123.")

    def test_report_generates_self_contained_html(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic One", "--priority", "1")
        run(self.root, "new", "task", "epic-one", "Task with </script> in the name", "--priority", "2")
        run(self.root, "new", "epic", "Epic Two", "--priority", "2", "--status", "complete")

        out = Path(self._tmp.name) / "report.html"
        rc, out_text, err = run(self.root, "report", "--out", str(out))
        self.assertEqual(rc, 0, err)
        self.assertTrue(out.exists())

        content = out.read_text(encoding="utf-8")
        self.assertEqual(content.count("<details"), content.count("</details>"))
        self.assertIn("Epic One", content)
        self.assertIn("Epic Two", content)
        # the literal </script> inside a name must be HTML-escaped in the visible markup...
        self.assertIn("&lt;/script&gt;", content)
        self.assertNotIn("<span class=\"name\">Task with </script>", content)

        import re
        m = re.search(r'<script id="kanban-data"[^>]*>(.*?)</script>', content, re.S)
        self.assertIsNotNone(m)
        # ...and must not have broken out of the embedded JSON <script> block either -- the JSON
        # still parses, and round-trips back to the original unescaped name.
        parsed = json.loads(m.group(1))
        self.assertEqual(len(parsed), 2)
        names = {c["name"] for e in parsed for c in e.get("children", [])}
        self.assertIn("Task with </script> in the name", names)

    def test_lint_catches_csv_json_drift(self):
        run(self.root, "init")
        run(self.root, "new", "epic", "Epic", "--priority", "1")
        run(self.root, "new", "task", "epic", "Task A", "--priority", "1")

        doc_path = self.root / "epic" / "task-a.json"
        record = json.loads(doc_path.read_text())
        record["status"] = "complete"
        doc_path.write_text(json.dumps(record))

        rc, out, err = run(self.root, "lint")
        self.assertNotEqual(rc, 0)
        self.assertIn("drift", out)


if __name__ == "__main__":
    unittest.main()
