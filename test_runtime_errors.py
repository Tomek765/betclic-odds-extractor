"""Common environment failures get a clear Polish message (raw text kept for diagnosis)."""
import unittest

from core import _friendly_runtime_error


class FriendlyRuntimeErrors(unittest.TestCase):
    def check(self, exc, code, fragment):
        got_code, message = _friendly_runtime_error(exc)
        self.assertEqual(got_code, code)
        self.assertIn(fragment, message)
        self.assertIn(str(exc)[:40], message)

    def test_profile_in_use(self):
        self.check(RuntimeError("Failed to create a ProcessSingleton for your profile directory"),
                   "BROWSER_PROFILE_IN_USE", "Zamknij inne okna programu")

    def test_browser_closed_by_user(self):
        self.check(RuntimeError("Target page, context or browser has been closed"),
                   "BROWSER_CLOSED", "nie zamykaj okna przeglądarki")

    def test_missing_browser(self):
        self.check(RuntimeError("Executable doesn't exist at C:\\x\\chrome.exe"),
                   "BROWSER_MISSING", "Zainstaluj ponownie")

    def test_network(self):
        self.check(RuntimeError("page.goto: net::ERR_INTERNET_DISCONNECTED"), "NETWORK_ERROR", "Sprawdź internet")

    def test_unknown_error_keeps_the_old_contract(self):
        code, message = _friendly_runtime_error(ValueError("boom"))
        self.assertEqual((code, message), ("UNHANDLED_EXCEPTION", "Błąd wykonania: boom"))


if __name__ == "__main__":
    unittest.main()
