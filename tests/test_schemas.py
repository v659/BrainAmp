import unittest

from pydantic import ValidationError

from app.schemas import AddSourceData, LoginData, PlannerTaskData, SignupData


class TestSchemas(unittest.TestCase):
    def test_login_data_valid(self):
        data = LoginData(email="user@example.com", username="user_1", password="longpassword")
        self.assertEqual(data.username, "user_1")

    def test_login_data_invalid_username(self):
        with self.assertRaises(ValidationError):
            LoginData(email="user@example.com", username="bad name", password="longpassword")

    def test_signup_data_invalid_username(self):
        with self.assertRaises(ValidationError):
            SignupData(email="user@example.com", username="bad!name", password="longpassword")

    def test_add_source_data_validates_domain(self):
        valid = AddSourceData(domain="Example.COM")
        self.assertEqual(valid.domain, "example.com")

        with self.assertRaises(ValidationError):
            AddSourceData(domain="invalid domain")

    def test_planner_task_limits(self):
        task = PlannerTaskData(date="2026-02-18", title="Study", time="09:30", notes="revise chapter 1")
        self.assertEqual(task.title, "Study")


if __name__ == "__main__":
    unittest.main()
