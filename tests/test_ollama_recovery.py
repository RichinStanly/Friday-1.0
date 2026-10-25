import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from friday.providers import OllamaLauncher


class _EmptyButRunningProvider:
    def __init__(self):
        self.checks = 0

    def is_running(self):
        self.checks += 1
        return True

    def available_models(self):
        return [object()] if self.checks > 1 else []


class OllamaRecoveryTests(unittest.TestCase):
    def test_empty_daemon_is_restarted_with_model_store_that_has_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_store = root / "models"
            manifest = model_store / "manifests" / "registry" / "library" / "test" / "latest"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}", encoding="utf-8")
            launcher = OllamaLauncher(_EmptyButRunningProvider())
            launcher._configured_models_dir = lambda: model_store
            launcher._find_executable = lambda: root / "ollama.exe"
            launcher._stop_empty_misconfigured_server = lambda: True
            launcher._POLL_INTERVAL = 0
            launcher._TIMEOUT = 0.1

            with patch("friday.providers.subprocess.Popen") as popen:
                self.assertTrue(launcher.ensure_running())

        self.assertEqual(popen.call_args.args[0][-1], "serve")
        self.assertEqual(popen.call_args.kwargs["env"]["OLLAMA_MODELS"], str(model_store))


if __name__ == "__main__":
    unittest.main()
