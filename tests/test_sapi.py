"""Optional Windows SAPI smoke check; enable explicitly on a machine with audio."""

import os
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("FRIDAY_TEST_SAPI") == "1", "requires explicit opt-in and Windows speech/audio")
class SapiSmokeTest(unittest.TestCase):
    def test_sapi_can_write_a_wav_file(self):
        import win32com.client

        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        output_path = os.path.join(tempfile.gettempdir(), "friday_sapi_smoke.wav")
        stream.Open(output_path, 3)
        try:
            speaker.AudioOutputStream = stream
            speaker.Speak("Friday speech system check.")
        finally:
            stream.Close()
        self.assertTrue(os.path.isfile(output_path))
        self.assertGreater(os.path.getsize(output_path), 44)
