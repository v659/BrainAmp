import unittest

from app.helpers import (
    get_account_settings_from_metadata,
    get_learning_assets_from_metadata,
    get_planner_state_from_metadata,
    is_ssl_or_network_auth_error,
    is_valid_time_hhmm,
    normalize_module_lookup_text,
    normalize_subject,
    parse_date_range_from_message,
    parse_iso_date_or_none,
    try_parse_date,
)


class TestHelpers(unittest.TestCase):
    def test_normalize_subject(self):
        self.assertEqual(normalize_subject("  computer   science "), "Computer Science")

    def test_is_valid_time_hhmm(self):
        self.assertTrue(is_valid_time_hhmm("9:30"))
        self.assertTrue(is_valid_time_hhmm("23:59"))
        self.assertFalse(is_valid_time_hhmm("24:00"))
        self.assertFalse(is_valid_time_hhmm("09:60"))
        self.assertFalse(is_valid_time_hhmm("bad"))

    def test_normalize_module_lookup_text(self):
        self.assertEqual(normalize_module_lookup_text('"the module Linear Algebra"'), "Linear Algebra")

    def test_try_parse_date_variants(self):
        self.assertIsNotNone(try_parse_date("2026-02-18"))
        self.assertIsNotNone(try_parse_date("February 18, 2026"))
        self.assertIsNone(try_parse_date("not-a-date"))

    def test_parse_iso_date_or_none(self):
        parsed = parse_iso_date_or_none("2026-02-18")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-02-18")
        self.assertIsNone(parse_iso_date_or_none("2026/02/18"))

    def test_parse_date_range_from_message(self):
        result = parse_date_range_from_message("show notes from 2026-01-01 to 2026-01-03")
        self.assertIsNotNone(result)
        start_dt, end_exclusive = result
        self.assertEqual(start_dt.strftime("%Y-%m-%d"), "2026-01-01")
        self.assertEqual(end_exclusive.strftime("%Y-%m-%d"), "2026-01-04")

    def test_get_account_settings_defaults(self):
        settings = get_account_settings_from_metadata({})
        self.assertTrue(settings["web_search_enabled"])
        self.assertEqual(settings["grade_level"], "")

    def test_get_learning_assets_defaults(self):
        assets = get_learning_assets_from_metadata({})
        self.assertEqual(assets, {"courses": [], "quizzes": []})

    def test_get_planner_state_defaults(self):
        state = get_planner_state_from_metadata({})
        self.assertEqual(state, {"busy_slots": [], "custom_tasks": [], "reminders": []})

    def test_is_ssl_or_network_auth_error(self):
        err = RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")
        self.assertTrue(is_ssl_or_network_auth_error(err))
        self.assertFalse(is_ssl_or_network_auth_error(RuntimeError("authentication failed")))


if __name__ == "__main__":
    unittest.main()
