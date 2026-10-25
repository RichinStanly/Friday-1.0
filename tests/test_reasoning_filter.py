import unittest

from friday.providers import _VisibleResponseFilter


class ReasoningFilterTests(unittest.TestCase):
    def test_hides_thinking_block(self):
        stream = _VisibleResponseFilter()
        result = "".join(stream.feed(part) for part in ("Answer. <thi", "nk>private thoughts</think> Done."))
        self.assertEqual(result + stream.feed("", final=True), "Answer.  Done.")


if __name__ == "__main__":
    unittest.main()
