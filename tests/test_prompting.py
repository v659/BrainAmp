import unittest

from app.prompting import load_prompt_text


class TestPrompting(unittest.TestCase):
    def test_load_prompt_text_with_replacements(self):
        content = load_prompt_text(
            "system/date_range_inference_user.txt",
            {"{LOCAL_DATE_ISO}": "2026-02-18", "{MESSAGE}": "What did I study yesterday?"},
        )
        self.assertIsInstance(content, str)
        self.assertIn("2026-02-18", content)
        self.assertIn("What did I study yesterday?", content)


if __name__ == "__main__":
    unittest.main()
