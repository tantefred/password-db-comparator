"""Tests für den inhaltlichen Vergleich von Zeit- und TOTP-Werten."""
import unittest

import tests.helpers  # noqa: F401  (richtet den Importpfad ein)
from csvcompare.service import analyze
from csvcompare.values import differing_columns, totp_key, values_equal

HEADER = "Group,Title,Username,Password,URL,Notes,TOTP,Icon,Last Modified,Created\n"


def csv_row(title="A", pw="pw", totp="", modified="2024-01-01T10:00:00Z",
            created="2023-01-01T09:00:00Z", group="Web", user="u", url=""):
    return f"{group},{title},{user},{pw},{url},,{totp},1,{modified},{created}\n"


def compare(old_rows, new_rows, options=None):
    return analyze("a.csv", HEADER + "".join(old_rows), "b.csv", HEADER + "".join(new_rows),
                   options or {})["report"]


class TimeEqualityTests(unittest.TestCase):
    def test_same_instant_in_different_notation_is_equal(self):
        base = "2024-01-01T10:00:00Z"
        for other in ("2024-01-01T10:00:00.000Z", "2024-01-01T10:00:00+00:00",
                      "2024-01-01T11:00:00+01:00", "2024-01-01 10:00:00",
                      "2024-01-01T10:00:00.789Z"):
            with self.subTest(other=other):
                self.assertTrue(values_equal("Last Modified", base, other))
                self.assertTrue(values_equal("Created", other, base))

    def test_different_instants_are_not_equal(self):
        self.assertFalse(values_equal("Last Modified", "2024-01-01T10:00:00Z",
                                      "2024-01-01T10:00:01Z"))
        self.assertFalse(values_equal("Created", "2024-01-01T10:00:00Z",
                                      "2024-01-01T10:00:00-01:00"))

    def test_unreadable_values_fall_back_to_exact_comparison(self):
        self.assertTrue(values_equal("Created", "gestern", "gestern"))
        self.assertFalse(values_equal("Created", "gestern", "heute"))
        self.assertFalse(values_equal("Created", "gestern", "2024-01-01T10:00:00Z"))
        self.assertFalse(values_equal("Created", "", "2024-01-01T10:00:00Z"))
        self.assertTrue(values_equal("Created", "", ""))

    def test_other_columns_are_compared_exactly(self):
        self.assertFalse(values_equal("Notes", "a", "A"))
        self.assertFalse(values_equal("Password", "x", "x "))
        self.assertTrue(values_equal("Password", "x", "x"))


class TotpEqualityTests(unittest.TestCase):
    URI = "otpauth://totp/Example:max?secret=JBSWY3DPEHPK3PXP&issuer=Example"

    def test_uri_and_plain_secret_are_equal(self):
        self.assertTrue(values_equal("TOTP", self.URI, "JBSWY3DPEHPK3PXP"))
        self.assertTrue(values_equal("TOTP", "jbswy3dp ehpk3pxp", "JBSWY3DPEHPK3PXP"))
        self.assertTrue(values_equal("TOTP", "JBSWY3DP-EHPK3PXP", self.URI))

    def test_different_secret_or_parameters_are_not_equal(self):
        self.assertFalse(values_equal("TOTP", self.URI, "JBSWY3DPEHPK3PXQ"))
        self.assertFalse(values_equal("TOTP", self.URI, self.URI + "&period=60"))
        self.assertFalse(values_equal("TOTP", self.URI, self.URI + "&digits=8"))
        self.assertFalse(values_equal("TOTP", self.URI, self.URI + "&algorithm=SHA256"))

    def test_defaults_are_taken_into_account(self):
        self.assertTrue(values_equal("TOTP", self.URI, self.URI + "&period=30&digits=6"))

    def test_empty_values(self):
        self.assertTrue(values_equal("TOTP", "", ""))
        self.assertFalse(values_equal("TOTP", "", self.URI))
        self.assertIsNone(totp_key("  "))


class DifferingColumnsTests(unittest.TestCase):
    def test_lists_only_real_differences(self):
        a = {"Password": "x", "Created": "2024-01-01T10:00:00Z", "TOTP": "JBSWY3DPEHPK3PXP"}
        b = {"Password": "y", "Created": "2024-01-01T10:00:00.000Z",
             "TOTP": "otpauth://totp/x?secret=jbswy3dpehpk3pxp"}
        self.assertEqual(differing_columns(a, b, ["Password", "Created", "TOTP"]), ["Password"])


class EndToEndTests(unittest.TestCase):
    def test_notation_only_differences_are_not_changes(self):
        old = [csv_row(totp="JBSWY3DPEHPK3PXP", modified="2024-01-01T10:00:00Z",
                       created="2023-01-01T09:00:00Z")]
        new = [csv_row(totp="otpauth://totp/x?secret=jbswy3dpehpk3pxp",
                       modified="2024-01-01T11:00:00+01:00", created="2023-01-01T09:00:00.000Z")]
        self.assertTrue(compare(old, new)["summary"]["identical"])

    def test_real_differences_are_still_found(self):
        old = [csv_row()]
        new = [csv_row(modified="2024-01-01T10:00:05Z")]
        r = compare(old, new)
        self.assertEqual(r["summary"]["changed"], 1)
        self.assertTrue(r["changed"]["newer_in_new"][0]["only_timestamp"])

    def test_move_is_certain_even_if_created_is_written_differently(self):
        old = [csv_row(title="Alt", group="Privat", created="2023-02-02T08:00:00Z")]
        new = [csv_row(title="Neu", group="Web", created="2023-02-02T09:00:00+01:00")]
        r = compare(old, new)
        self.assertEqual(len(r["moved"]), 1)
        self.assertEqual(r["moved"][0]["confidence"], "certain")

    def test_merge_has_no_conflict_for_notation_only_differences(self):
        old = [csv_row(modified="2024-01-01T10:00:00Z")]
        new = [csv_row(modified="2024-01-01T10:00:00.000Z")]
        result = analyze("a.csv", HEADER + "".join(old), "b.csv", HEADER + "".join(new),
                         {"export_merged": True})
        self.assertEqual(result["exports"]["merged"]["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
