"""Tests des Bitwarden/Vaultwarden-CSV-Importers."""
import csv
import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from csvcompare.columns import ALL_NAMES, SOURCE_KEY  # noqa: E402
from csvcompare.importers import CsvError, load_any  # noqa: E402
from csvcompare.service import analyze  # noqa: E402

HEADER = ["folder", "favorite", "type", "name", "notes", "fields", "reprompt",
          "login_uri", "login_username", "login_password", "login_totp"]


def read(name):
    with open(os.path.join(ROOT, "tests", name), encoding="utf-8", newline="") as f:
        return f.read()


CSV_TEXT = read("bitwarden.csv")
JSON_TEXT = read("bitwarden.json")


def make_csv(rows, header=HEADER):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def row(folder="", favorite="", type_="login", name="X", notes="", fields="", reprompt="0",
        uri="", user="", pw="", totp=""):
    return [folder, favorite, type_, name, notes, fields, reprompt, uri, user, pw, totp]


def by_title(text=CSV_TEXT):
    result = load_any("bw.csv", text)
    return result, {r["Title"]: r for r in result.rows}


class MappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.rows = by_title()

    def test_format_and_provided_columns(self):
        self.assertEqual(self.result.format, "bitwarden-csv")
        self.assertEqual(self.result.provided_columns,
                         frozenset(ALL_NAMES) - {"Icon", "Last Modified", "Created"})

    def test_logins_and_notes_are_imported(self):
        self.assertEqual(len(self.result.rows), 8)

    def test_every_row_has_every_column(self):
        for r in self.result.rows:
            for name in ALL_NAMES:
                self.assertIsInstance(r[name], str)

    def test_login_fields(self):
        mail = self.rows["Mail"]
        self.assertEqual((mail["Group"], mail["Username"], mail["Password"]),
                         ("Web", "max@example.org", "pw-mail-1"))
        self.assertEqual(mail["URL"], "https://mail.example.org")
        self.assertEqual(mail["Favorite"], "1")
        self.assertEqual(mail["Type"], "login")
        self.assertEqual(self.rows["Forum"]["Favorite"], "0")
        self.assertEqual(self.rows["Bank"]["Reprompt"], "1")

    def test_missing_timestamps_and_icon_stay_empty(self):
        for r in self.result.rows:
            self.assertEqual((r["Icon"], r["Last Modified"], r["Created"]), ("", "", ""))

    def test_multiple_urls(self):
        shop = self.rows["Shop"]
        self.assertEqual(shop["URL"], "https://shop.example.org")
        self.assertEqual(shop["URLs"], "https://shop.example.org\nhttps://shop.example.org/login")

    def test_multiline_notes(self):
        self.assertEqual(self.rows["Shop"]["Notes"], "Zeile 1\nZeile 2")

    def test_fields_are_kept_as_text(self):
        self.assertEqual(self.rows["Mail"]["Fields"], "PIN: 1234 Konto: Haupt konto")

    def test_secure_note(self):
        note = self.rows["WLAN-Zugang"]
        self.assertEqual((note["Type"], note["Password"], note["Notes"]),
                         ("note", "", "SSID: Heimnetz"))

    def test_note_explains_missing_timestamps(self):
        self.assertIn("keine Zeitstempel", self.result.notes[-1])


class FieldsTests(unittest.TestCase):
    def fields_of(self, value):
        return load_any("x.csv", make_csv([row(fields=value)])).rows[0]["Fields"]

    def test_space_separated_newline_separated_and_padded_are_equal(self):
        spaced = "PIN: 1234 Konto: Haupt konto"
        self.assertEqual(self.fields_of("PIN: 1234\nKonto: Haupt konto"), spaced)
        self.assertEqual(self.fields_of("PIN: 1234\r\nKonto: Haupt konto"), spaced)
        self.assertEqual(self.fields_of("  PIN: 1234   Konto:  Haupt konto  "), spaced)
        self.assertEqual(self.fields_of(spaced), spaced)

    def test_different_content_is_still_different(self):
        self.assertNotEqual(self.fields_of("PIN: 1234"), self.fields_of("PIN: 1235"))

    def test_original_text_stays_in_the_source(self):
        original = "PIN: 1234\nKonto: Haupt konto"
        r = load_any("x.csv", make_csv([row(fields=original)])).rows[0]
        self.assertEqual(r[SOURCE_KEY]["fields"], original)


class MatchesJsonImportTests(unittest.TestCase):
    """Dieselben Einträge aus JSON und CSV müssen in allen gemeinsamen Spalten gleich sein."""

    COMMON = ["Group", "Title", "Username", "Password", "URL", "URLs", "Notes", "TOTP",
              "Favorite", "Type", "Reprompt", "Fields"]

    def test_rows_agree(self):
        _, csv_rows = by_title(CSV_TEXT)
        json_result = load_any("bw.json", JSON_TEXT)
        json_rows = {r["Title"]: r for r in json_result.rows}
        shared = set(csv_rows) & set(json_rows)
        self.assertEqual(len(shared), 8)
        for title in shared:
            for col in self.COMMON:
                with self.subTest(title=title, column=col):
                    self.assertEqual(csv_rows[title][col], json_rows[title][col])


class RobustnessTests(unittest.TestCase):
    def test_other_types_are_skipped_and_counted(self):
        text = make_csv([row(name="A"), row(type_="card", name="Karte"),
                         row(type_="identity", name="Person"), row(type_="card", name="K2")])
        result = load_any("x.csv", text)
        self.assertEqual([r["Title"] for r in result.rows], ["A"])
        self.assertIn("3 Einträge übersprungen (2 card, 1 identity)", result.notes[0])

    def test_missing_optional_columns_are_tolerated(self):
        header = ["name", "login_uri", "login_username", "login_password"]
        result = load_any("x.csv", make_csv([["A", "https://a.example", "u", "p"]], header))
        r = result.rows[0]
        self.assertEqual((r["Title"], r["Group"], r["Fields"], r["Favorite"]), ("A", "", "", "0"))

    def test_switches_accept_the_usual_spellings(self):
        for on in ("1", "true", "True", "TRUE", " 1 "):
            r = load_any("x.csv", make_csv([row(favorite=on, reprompt=on)])).rows[0]
            self.assertEqual((r["Favorite"], r["Reprompt"]), ("1", "1"), on)
        for off in ("", "0", "false", "False", "nein"):
            r = load_any("x.csv", make_csv([row(favorite=off, reprompt=off)])).rows[0]
            self.assertEqual((r["Favorite"], r["Reprompt"]), ("0", "0"), off)

    def test_empty_export(self):
        self.assertEqual(load_any("x.csv", make_csv([])).rows, [])

    def test_utf8_bom_is_accepted(self):
        self.assertEqual(len(load_any("bw.csv", chr(0xFEFF) + CSV_TEXT).rows), 8)

    def test_unknown_csv_is_still_reported_as_missing_columns(self):
        with self.assertRaises(CsvError) as ctx:
            load_any("fremd.csv", "a,b\n1,2\n")
        self.assertIn("fehlen Spalten", str(ctx.exception))

    def test_keepass_csv_is_not_mistaken_for_bitwarden(self):
        self.assertEqual(load_any("alt.csv", read("alt.csv")).format, "keepass-csv")

    def test_json_is_not_mistaken_for_csv(self):
        self.assertEqual(load_any("bw.json", JSON_TEXT).format, "bitwarden-json")


class ComparisonTests(unittest.TestCase):
    def compare(self, old_text, new_text, options=None):
        return analyze("a.csv", old_text, "b.csv", new_text, options or {})["report"]

    def test_file_with_itself_is_identical(self):
        self.assertTrue(self.compare(CSV_TEXT, CSV_TEXT)["summary"]["identical"])

    def test_format_and_note_appear_in_the_report(self):
        files = self.compare(CSV_TEXT, CSV_TEXT)["files"]
        self.assertEqual(files["old"]["format"], "bitwarden-csv")
        self.assertIn("keine Zeitstempel", files["old"]["notes"][-1])

    def test_changes_have_unclear_freshness_without_timestamps(self):
        new = CSV_TEXT.replace("pw-forum", "pw-forum-2")
        r = self.compare(CSV_TEXT, new)
        self.assertEqual(r["summary"]["changed"], 1)
        self.assertEqual([i["entry"]["title"] for i in r["changed"]["unclear"]], ["Forum"])
        self.assertEqual(r["changed"]["newer_in_new"], [])
        self.assertEqual(r["changed"]["newer_in_old"], [])

    def test_a_renamed_entry_is_found_as_a_likely_move(self):
        new = CSV_TEXT.replace(",Bank,", ",Girokonto,")
        r = self.compare(CSV_TEXT, new)
        self.assertEqual(len(r["moved"]), 1)
        self.assertEqual(r["moved"][0]["confidence"], "likely")
        self.assertEqual(r["moved"][0]["moved_to"]["title"], "Girokonto")

    def test_passwords_stay_masked(self):
        new = CSV_TEXT.replace("pw-forum", "pw-forum-2")
        self.assertNotIn("pw-forum", json.dumps(self.compare(CSV_TEXT, new)))


if __name__ == "__main__":
    unittest.main()
