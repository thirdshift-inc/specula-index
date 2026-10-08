import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


class PinnedActions(unittest.TestCase):
    def test_every_action_is_pinned_to_a_full_commit_id(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            lines = path.read_text(encoding="utf-8").splitlines()
            uses = [n for n, line in enumerate(lines) if line.lstrip(" -").startswith("uses:")]
            self.assertTrue(uses, path.name)
            for n in uses:
                with self.subTest(workflow=path.name, line=n + 1):
                    self.assertRegex(lines[n], r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
