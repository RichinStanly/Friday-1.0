import unittest

from friday.chat import ChatEngine
from friday.models import LocalModel


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.chat = ChatEngine(store=None, provider=None, tools=None)

    def test_selected_vision_and_prompt_models_are_respected(self):
        self.chat.update_routing({"vision": "vision-custom", "image_prompt": "prompt-custom"})
        models = [LocalModel(name="vision-custom"), LocalModel(name="prompt-custom")]
        self.assertEqual(self.chat._vision_model(models, "FRIDAY Auto"), "vision-custom")
        self.assertEqual(self.chat._dolphin_model(), "prompt-custom")

    def test_selected_chat_model_and_tool_model_are_retained(self):
        self.chat.update_routing({"default_chat": "chat-custom", "tool_routing": "tool-custom"})
        self.assertEqual(self.chat._default_chat_model(), "chat-custom")
        self.assertEqual(self.chat._tool_routing_model(), "tool-custom")

    def test_missing_vision_route_falls_back_to_installed_vision_model(self):
        self.chat.update_routing({"vision": "not-installed"})
        self.assertEqual(self.chat._vision_model([LocalModel(name="qwen3-vl:8b")]), "qwen3-vl:8b")


if __name__ == "__main__":
    unittest.main()
