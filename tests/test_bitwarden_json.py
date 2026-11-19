"""Tests des Bitwarden/Vaultwarden-JSON-Importers."""
import copy
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from csvcompare.columns import ALL_NAMES, SOURCE_KEY  # noqa: E402
from csvcompare.importers import CsvError, load_any  # noqa: E402
from csvcompare.service import analyze  # noqa: E402

PATH = os.path.join(ROOT, "tests", "bitwarden.json")
with open(PATH, encoding="utf-8") as f:
    TEXT = f.read()
DATA = json.loads(TEXT)


def rows_by_title(text=TEXT):
    result = load_any("bw.json", text)
    return result, {r["Title"]: r for r in result.rows}


def modified(mutator):
    data = copy.deepcopy(DATA)
    mutator(data)
    return json.dumps(data)


class MappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result, cls.rows = rows_by_title()

    def test_format_and_provided_columns(self):
        self.assertEqual(self.result.format, "bitwarden-json")
        self.assertEqual(self.result.provided_columns, frozenset(ALL_NAMES) - {"Icon"})

    def test_logins_and_secure_notes_are_imported(self):
        self.assertEqual(len(self.result.rows), 9)
        self.assertNotIn("Kreditkarte", self.rows)
        self.assertNotIn("Personalien", self.rows)

    def test_every_row_has_every_column(self):
        for row in self.result.rows:
            for name in ALL_NAMES:
                self.assertIn(name, row)
                self.assertIsInstance(row[name], str)

    def test_login_fields(self):
        mail = self.rows["Mail"]
        self.assertEqual(mail["Group"], "Web")
        self.assertEqual(mail["Username"], "max@example.org")
        self.assertEqual(mail["Password"], "pw-mail-1")
        self.assertEqual(mail["URL"], "https://mail.example.org")
        self.assertEqual(mail["Notes"], "")
        self.assertEqual(mail["TOTP"], "otpauth://totp/Mail:max?secret=JBSWY3DPEHPK3PXP&issuer=Mail")
        self.assertEqual(mail["Icon"], "")

    def test_timestamps_are_normalised(self):
        mail = self.rows["Mail"]
        self.assertEqual(mail["Last Modified"], "2024-01-10T10:00:00Z")
        self.assertEqual(mail["Created"], "2023-01-01T09:00:00Z")

    def test_extra_columns(self):
        mail = self.rows["Mail"]
        self.assertEqual(mail["Favorite"], "1")
        self.assertEqual(mail["Type"], "login")
        self.assertEqual(mail["Reprompt"], "0")
        self.assertEqual(mail["Fields"], "PIN: 1234 Konto: Haupt konto")
        self.assertEqual(self.rows["Bank"]["Reprompt"], "1")
        self.assertEqual(self.rows["Forum"]["Favorite"], "0")

    def test_all_urls_are_kept_and_the_first_is_the_url(self):
        shop = self.rows["Shop"]
        self.assertEqual(shop["URL"], "https://shop.example.org")
        self.assertEqual(shop["URLs"], "https://shop.example.org\nhttps://shop.example.org/login")
        self.assertEqual(self.rows["Alt-Account"]["URL"], "")
        self.assertEqual(self.rows["Alt-Account"]["URLs"], "")

    def test_multiline_notes_are_kept(self):
        self.assertEqual(self.rows["Shop"]["Notes"], "Zeile 1\nZeile 2")

    def test_folders_become_groups(self):
        self.assertEqual(self.rows["Shop"]["Group"], "Web/Shops")
        self.assertEqual(self.rows["Bank"]["Group"], "Privat")
        self.assertEqual(self.rows["Router"]["Group"], "")

    def test_deleted_items_go_to_the_trash_group(self):
        self.assertEqual(self.rows["Gelöscht"]["Group"], "Papierkorb")

    def test_secure_note_has_no_password(self):
        note = self.rows["WLAN-Zugang"]
        self.assertEqual(note["Type"], "note")
        self.assertEqual(note["Password"], "")
        self.assertEqual(note["Notes"], "SSID: Heimnetz")
        self.assertEqual(note["Group"], "Privat")

    def test_notes_name_skipped_types_and_deleted_entries(self):
        self.assertEqual(len(self.result.notes), 2)
        self.assertIn("2 Einträge übersprungen (1 Karte, 1 Identität)", self.result.notes[0])
        self.assertIn("1 gelöschter Eintrag", self.result.notes[1])


class NothingIsLostTests(unittest.TestCase):
    def test_original_item_is_kept_untouched(self):
        result, rows = rows_by_title()
        by_id = {item["id"]: item for item in DATA["items"]}
        for row in result.rows:
            self.assertEqual(row[SOURCE_KEY], by_id[row[SOURCE_KEY]["id"]])

    def test_data_that_is_not_compared_survives_in_the_source(self):
        _, rows = rows_by_title()
        source = rows["Mail"][SOURCE_KEY]
        self.assertEqual(source["passwordHistory"][0]["password"], "pw-mail-0")
        self.assertEqual(source["login"]["uris"][0]["match"], None)
        self.assertEqual(source["fields"][0]["type"], 1)
        self.assertEqual(source["id"], "0001")
        self.assertEqual(source["folderId"], "f-web")
        self.assertEqual(rows["Gelöscht"][SOURCE_KEY]["deletedDate"], "2024-02-02T00:00:00.000Z")

    def test_every_key_of_every_imported_item_is_present(self):
        result, _ = rows_by_title()
        imported = {row[SOURCE_KEY]["id"] for row in result.rows}
        for item in DATA["items"]:
            if item["id"] in imported:
                row_source = next(r[SOURCE_KEY] for r in result.rows
                                  if r[SOURCE_KEY]["id"] == item["id"])
                self.assertEqual(set(row_source), set(item))

    def test_source_never_appears_in_reports(self):
        report = analyze("a.json", TEXT, "b.json", TEXT, {})["report"]
        self.assertNotIn(SOURCE_KEY, json.dumps(report))
        self.assertNotIn("passwordHistory", json.dumps(report))


class ErrorTests(unittest.TestCase):
    def test_encrypted_export(self):
        text = json.dumps({"encrypted": True, "encKeyValidation_DO_NOT_EDIT": "2.x", "data": "2.y"})
        with self.assertRaises(CsvError) as ctx:
            load_any("verschluesselt.json", text)
        self.assertIn("verschlüsselter Bitwarden-Export", str(ctx.exception))
        self.assertIn("verschluesselt.json", str(ctx.exception))

    def test_invalid_json(self):
        with self.assertRaises(CsvError) as ctx:
            load_any("kaputt.json", '{"items": [')
        self.assertIn("kein gültiges JSON", str(ctx.exception))

    def test_json_that_is_not_a_bitwarden_export(self):
        for text in ('{"foo": 1}', '[1, 2]', '{"items": "x"}'):
            with self.subTest(text=text):
                with self.assertRaises(CsvError) as ctx:
                    load_any("x.json", text)
                self.assertIn("nicht wie ein Bitwarden", str(ctx.exception))

    def test_incomplete_items_do_not_crash(self):
        text = json.dumps({"folders": None, "items": [
            {"type": 1}, {"type": 1, "name": None, "login": None, "fields": "kaputt"},
            "kein Objekt", {"type": 1, "name": "X", "login": {"uris": [None, {"uri": None}, 5]}},
            {"type": 99, "name": "Unbekannt"}]})
        result = load_any("x.json", text)
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(result.rows[2]["URL"], "")
        self.assertIn("1 Eintrag übersprungen (1 Typ 99)", result.notes[0])

    def test_empty_export(self):
        result = load_any("leer.json", '{"items": []}')
        self.assertEqual(result.rows, [])

    def test_utf8_bom_is_accepted(self):
        self.assertEqual(len(load_any("bw.json", chr(0xFEFF) + TEXT).rows), 9)


class IntegrationTests(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "compare_csv.py"), *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout, proc.stderr

    def test_file_with_itself_is_identical(self):
        rc, out, _ = self.run_cli("tests/bitwarden.json", "tests/bitwarden.json")
        self.assertEqual(rc, 0)
        self.assertIn("Keine Unterschiede.", out)

    def test_header_shows_the_importer_notes(self):
        _, out, _ = self.run_cli("tests/bitwarden.json", "tests/bitwarden.json")
        self.assertIn("Hinweis: 2 Einträge übersprungen (1 Karte, 1 Identität)", out)

    def test_changes_between_two_exports_are_found(self):
        def change(data):
            by_name = {i["name"]: i for i in data["items"]}
            by_name["Mail"]["login"]["password"] = "neu"
            by_name["Mail"]["revisionDate"] = "2025-01-01T00:00:00.000Z"
            by_name["Forum"]["notes"] = "Hallo"
            del data["items"][data["items"].index(by_name["Router"])]
        report = analyze("a.json", TEXT, "b.json", modified(change), {})["report"]
        s = report["summary"]
        self.assertEqual((s["only_in_old"], s["only_in_new"], s["changed"]), (1, 0, 2))
        self.assertEqual(report["files"]["old"]["format"], "bitwarden-json")
        self.assertEqual(report["files"]["old"]["notes"][0][:20], "2 Einträge übersprun")
        mail = next(i for i in report["changed"]["newer_in_new"] if i["entry"]["title"] == "Mail")
        self.assertTrue(mail["changes"]["Password"]["masked"])

    def test_detection_does_not_break_csv_files(self):
        rc, out, _ = self.run_cli("tests/alt.csv", "tests/neu.csv")
        self.assertEqual(rc, 0)
        self.assertIn("Zusammenfassung", out)


if __name__ == "__main__":
    unittest.main()
