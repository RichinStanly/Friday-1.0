import io
import unittest
from unittest.mock import Mock

from friday.providers import OllamaProvider


class OllamaProviderTests(unittest.TestCase):
    def test_startup_load_requests_model_without_generating_text(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"response":""}'))
        response.__exit__ = Mock(return_value=False)
        provider = OllamaProvider()
        provider._request = Mock(return_value=response)

        provider.load_model("qwen2.5:7b", keep_alive="5m")

        provider._request.assert_called_once_with(
            "/api/generate",
            {"model": "qwen2.5:7b", "prompt": "", "stream": False, "keep_alive": "5m"},
            timeout=600,
        )


if __name__ == "__main__":
    unittest.main()
