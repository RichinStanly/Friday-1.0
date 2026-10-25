from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from friday.storage import LocalStore


class ConversationControlsPersistenceTests(unittest.TestCase):
    def test_per_conversation_controls_management_search_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "friday.db"
            store = LocalStore(database)
            first = store.new_conversation("FRIDAY Auto", web_enabled=False)
            second = store.new_conversation("qwen2.5:7b", web_enabled=True)
            store.save_message(second.id, "user", "Spider Gwen reference notes")
            store.set_conversation_options(second.id, web_enabled=False, memory_enabled=False, incognito=True)
            store.rename_conversation(second.id, "Spider Gwen")
            store.set_pinned(second.id, True)

            opened = store.get_conversation(second.id)
            self.assertEqual(opened.title, "Spider Gwen")
            self.assertEqual(opened.model, "qwen2.5:7b")
            self.assertFalse(opened.web_enabled)
            self.assertFalse(opened.memory_enabled)
            self.assertTrue(opened.incognito)
            self.assertTrue(opened.pinned)
            self.assertEqual(store.conversations("Spider Gwen")[0].id, second.id)
            self.assertEqual(store.conversations()[0].id, second.id)

            store.set_archived(second.id, True)
            self.assertNotIn(second.id, [conversation.id for conversation in store.conversations()])
            self.assertIn(second.id, [conversation.id for conversation in store.conversations(include_archived=True)])

            # Simulates a Friday restart: fields must survive a new LocalStore.
            reopened_store = LocalStore(database)
            restored = reopened_store.get_conversation(second.id)
            self.assertTrue(restored.archived)
            self.assertTrue(restored.pinned)
            self.assertFalse(restored.web_enabled)
            self.assertFalse(restored.memory_enabled)
            self.assertTrue(restored.incognito)
            self.assertEqual(reopened_store.get_conversation(first.id).model, "FRIDAY Auto")


if __name__ == "__main__":
    unittest.main()
