"""
Unit tests for core.parser. Run with:
    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.parser import extract_text, ParsingError  # noqa: E402


class TestParser(unittest.TestCase):

    def test_extract_txt(self):
        text = extract_text("resume.txt", b"Python Developer with Django experience.")
        self.assertIn("Python Developer", text)

    def test_unsupported_extension_raises(self):
        with self.assertRaises(ParsingError):
            extract_text("resume.rtf", b"some content")

    def test_empty_txt_raises(self):
        with self.assertRaises(ParsingError):
            extract_text("resume.txt", b"   \n\n  ")

    def test_normalise_collapses_whitespace(self):
        text = extract_text("resume.txt", b"Line1\n\n\n\n\nLine2   with   spaces")
        self.assertNotIn("\n\n\n", text)


if __name__ == "__main__":
    unittest.main()
