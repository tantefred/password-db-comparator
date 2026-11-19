"""Tests für den Vergleich über Formatgrenzen hinweg (KeePass-CSV, Bitwarden-JSON/-CSV)."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from csvcompare.compare import comparable_columns  # noqa: E402
from csvcompare.importers import load_any  # noqa: E402
from csvcompare.service import analyze  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, "tests", name), encoding="utf-8", newline="") as f:
        return f.read()


KP_A, KP_B = read("keepassium_a.csv"), read("keepassium_b.csv")
BW_JSON, BW_CSV = read("bitwarden.json"), read("bitwarden.csv")
BW_DATA = json.loads(BW_JSON)


def compare(old_name, old, new_name, new, options=None):
    return analyze(old_name, old, new_name, new, options or {})["report"]


def titles(entries):
    return sorted(e["title"] for e in entries)


def auto_ignored(report):
    return {a["column"]: a["reason"] for a in report["filters"]["auto_ignored"]}


def with_json(mutator):
    data = copy.deepcopy(BW_DATA)
    mutator(data)
    return json.dumps(data)


def item(data, name):
    return next(i for i in data["items"] if i["name"] == name)


class KeePassAgainstBitwardenJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = compare("kp.csv", KP_A, "bw.json", BW_JSON)

    def test_only_the_extra_note_differs(self):
        s = self.r["summary"]
        self.assertEqual((s["only_in_old"], s["only_in_new"], s["moved"], s["changed"]),
                         (0, 1, 0, 0))
        self.assertEqual(titles(self.r["only_in_new"]), ["WLAN-Zugang"])

    def test_formats_are_reported(self):
        self.assertEqual(self.r["files"]["old"]["format"], "keepass-csv")
        self.assertEqual(self.r["files"]["new"]["format"], "bitwarden-json")

    def test_columns_one_side_lacks_are_skipped_with_a_reason(self):
        skipped = auto_ignored(self.r)
        self.assertEqual(set(skipped), {"Icon", "Last Modified", "Created", "Favorite", "Type",
                                        "Reprompt", "Fields", "URLs"})
        self.assertIn("bw.json nicht vor", skipped["Icon"])
        self.assertIn("kp.csv nicht vor", skipped["Fields"])
        self.assertIn("nicht vergleichbar", skipped["Created"])

    def test_totp_notation_and_time_notation_do_not_matter(self):
        # Mail: reines Secret gegen otpauth-Link, Zeiten mit/ohne Millisekunden
        self.assertEqual(self.r["changed"], {"newer_in_new": [], "newer_in_old": [], "unclear": []})

    def test_trash_entry_matches_the_trash_group(self):
        s = compare("kp.csv", KP_A, "bw.json", BW_JSON, {"hide_trash": True})["summary"]
        self.assertEqual((s["only_in_old"], s["only_in_new"], s["changed"]), (0, 1, 0))

    def test_text_header_explains_the_skipped_columns(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run(
                [sys.executable, os.path.join(ROOT, "compare_csv.py"),
                 os.path.join(ROOT, "tests", "keepassium_a.csv"),
                 os.path.join(ROOT, "tests", "bitwarden.json")],
                capture_output=True, text=True, encoding="utf-8", cwd=d).stdout
        self.assertIn("(Bitwarden-JSON)", out)
        self.assertIn("Automatisch ausgelassen (kommt in bitwarden.json nicht vor): Icon", out)
        self.assertIn("Favorite, Type, Reprompt, Fields, URLs", out)


class KeePassAgainstBitwardenCsvTests(unittest.TestCase):
    def test_differences_are_only_what_the_formats_cannot_hold(self):
        r = compare("kp.csv", KP_A, "bw.csv", BW_CSV)
        self.assertEqual(titles(r["only_in_old"]), ["Gelöscht"])   # CSV-Export hat keinen Papierkorb
        self.assertEqual(titles(r["only_in_new"]), ["WLAN-Zugang"])
        self.assertEqual(r["summary"]["changed"], 0)
        self.assertEqual(set(auto_ignored(r)),
                         {"Icon", "Last Modified", "Created", "Favorite", "Type", "Reprompt",
                          "Fields", "URLs"})


class BitwardenJsonAgainstCsvTests(unittest.TestCase):
    def test_all_shared_columns_are_compared_and_equal(self):
        r = compare("bw.json", BW_JSON, "bw.csv", BW_CSV)
        self.assertEqual(titles(r["only_in_old"]), ["Gelöscht"])
        self.assertEqual(r["summary"]["changed"], 0)
        # Favorit, Typ, Nachfrage, Felder und URLs werden verglichen; nur die Zeitstempel fehlen
        # im CSV. Das Icon kennt keines der beiden Formate und wird deshalb nicht erwähnt.
        self.assertEqual(set(auto_ignored(r)), {"Last Modified", "Created"})


class SameFormatIsUnchangedTests(unittest.TestCase):
    def test_two_keepass_exports_skip_nothing(self):
        r = compare("a.csv", KP_A, "b.csv", KP_B)
        self.assertEqual(r["filters"]["auto_ignored"], [])

    def test_two_json_exports_compare_everything_they_have(self):
        r = compare("a.json", BW_JSON, "b.json", BW_JSON)
        self.assertEqual(auto_ignored(r), {})
        self.assertTrue(r["summary"]["identical"])


class RealDifferencesAcrossFormatsTests(unittest.TestCase):
    def test_changed_password_is_found_and_newer_side_is_known(self):
        def change(data):
            m = item(data, "Mail")
            m["login"]["password"] = "pw-mail-2"
            m["revisionDate"] = "2025-01-01T00:00:00.000Z"
        r = compare("kp.csv", KP_A, "bw.json", with_json(change))
        self.assertEqual(titles(i["entry"] for i in r["changed"]["newer_in_new"]), ["Mail"])
        mail = r["changed"]["newer_in_new"][0]
        self.assertEqual(mail["differing_columns"], ["Password"])
        self.assertTrue(mail["changes"]["Password"]["masked"])

    def test_edit_in_the_keepass_file_after_the_import_is_recognised(self):
        kp = KP_A.replace("pw-mail-1,https://mail.example.org", "pw-mail-9,https://mail.example.org")
        kp = kp.replace("2024-01-10T10:00:00Z", "2025-06-01T10:00:00Z")
        r = compare("kp.csv", kp, "bw.json", BW_JSON)
        self.assertEqual(titles(i["entry"] for i in r["changed"]["newer_in_old"]), ["Mail"])

    def test_timestamps_alone_are_no_difference_between_formats(self):
        def change(data):
            item(data, "Forum")["revisionDate"] = "2030-01-01T00:00:00.000Z"
        r = compare("kp.csv", KP_A, "bw.json", with_json(change))
        self.assertEqual(r["summary"]["changed"], 0)

    def test_timestamps_alone_are_a_difference_within_one_format(self):
        def change(data):
            item(data, "Forum")["revisionDate"] = "2030-01-01T00:00:00.000Z"
        r = compare("a.json", BW_JSON, "b.json", with_json(change))
        self.assertEqual(r["summary"]["changed"], 1)
        self.assertTrue(r["changed"]["newer_in_new"][0]["only_timestamp"])

    def test_renamed_folder_is_a_certain_move(self):
        def change(data):
            data["folders"][2]["name"] = "Finanzen"          # Ordner "Privat" umbenannt
        r = compare("kp.csv", KP_A, "bw.json", with_json(change))
        moved = {m["entry"]["title"]: m for m in r["moved"]}
        self.assertEqual(set(moved), {"Bank", "Streaming"})
        self.assertEqual(moved["Bank"]["confidence"], "certain")
        self.assertEqual(moved["Bank"]["changed_key_columns"], ["Group"])
        self.assertEqual(moved["Bank"]["moved_to"]["group"], "Finanzen")

    def test_without_timestamps_a_move_is_only_likely(self):
        csv_text = BW_CSV.replace("Privat,,login,Bank", "Finanzen,,login,Bank")
        r = compare("kp.csv", KP_A, "bw.csv", csv_text)
        bank = next(m for m in r["moved"] if m["entry"]["title"] == "Bank")
        self.assertEqual(bank["confidence"], "likely")

    def test_change_without_timestamps_has_unclear_freshness(self):
        csv_text = BW_CSV.replace("pw-forum", "pw-forum-2")
        r = compare("kp.csv", KP_A, "bw.csv", csv_text)
        self.assertEqual(titles(i["entry"] for i in r["changed"]["unclear"]), ["Forum"])


class ExtendedColumnsTests(unittest.TestCase):
    def changed_columns(self, mutator):
        r = compare("a.json", BW_JSON, "b.json", with_json(mutator))
        self.assertEqual(r["summary"]["changed"], 1)
        change = r["changed"]["newer_in_new"] + r["changed"]["newer_in_old"] + r["changed"]["unclear"]
        return change[0]["entry"]["title"], change[0]["differing_columns"], change[0]["changes"]

    def test_favorite(self):
        title, cols, _ = self.changed_columns(lambda d: item(d, "Forum").update(favorite=True))
        self.assertEqual((title, cols), ("Forum", ["Favorite"]))

    def test_reprompt(self):
        _, cols, _ = self.changed_columns(lambda d: item(d, "Forum").update(reprompt=1))
        self.assertEqual(cols, ["Reprompt"])

    def test_type(self):
        _, cols, _ = self.changed_columns(lambda d: item(d, "WLAN-Zugang").update(type=1, login={}))
        self.assertIn("Type", cols)

    def test_additional_url(self):
        def change(d):
            item(d, "Forum")["login"]["uris"].append({"match": None, "uri": "https://forum2.example"})
        _, cols, changes = self.changed_columns(change)
        self.assertEqual(cols, ["URLs"])
        self.assertIn("forum2.example", changes["URLs"]["new"])

    def test_custom_field_changes_are_found_and_masked(self):
        def change(d):
            item(d, "Mail")["fields"][0]["value"] = "9999"
        _, cols, changes = self.changed_columns(change)
        self.assertEqual(cols, ["Fields"])
        self.assertTrue(changes["Fields"]["masked"])
        self.assertNotIn("1234", json.dumps(changes))
        self.assertNotIn("9999", json.dumps(changes))

    def test_custom_field_changes_show_with_secrets_enabled(self):
        def change(d):
            item(d, "Mail")["fields"][0]["value"] = "9999"
        r = analyze("a.json", BW_JSON, "b.json", with_json(change), {"show_secrets": True})["report"]
        changes = r["changed"]["newer_in_new"][0]["changes"] if r["changed"]["newer_in_new"] \
            else r["changed"]["unclear"][0]["changes"]
        self.assertEqual(changes["Fields"]["old"], "PIN: 1234 Konto: Haupt konto")
        self.assertEqual(changes["Fields"]["new"], "PIN: 9999 Konto: Haupt konto")

    def test_extended_columns_can_be_ignored(self):
        def change(d):
            item(d, "Forum")["favorite"] = True
        r = compare("a.json", BW_JSON, "b.json", with_json(change), {"ignore": ["favorite"]})
        self.assertEqual(r["summary"]["changed"], 0)
        self.assertEqual(r["filters"]["ignored_columns"], ["Favorite"])

    def test_unknown_column_is_still_rejected(self):
        with self.assertRaises(Exception) as ctx:
            analyze("a.json", BW_JSON, "b.json", BW_JSON, {"ignore": ["Foo"]})
        self.assertIn("Unbekannte Spalte", str(ctx.exception))
        self.assertIn("Fields", str(ctx.exception))   # neue Spalten stehen in der Liste

    def test_user_ignored_columns_are_not_listed_as_automatic(self):
        r = compare("kp.csv", KP_A, "bw.json", BW_JSON, {"ignore": ["Icon"]})
        self.assertNotIn("Icon", auto_ignored(r))
        self.assertEqual(r["filters"]["ignored_columns"], ["Icon"])


class ComparableColumnsTests(unittest.TestCase):
    def sources(self, a, b):
        return load_any("a", a), load_any("b", b)

    def test_same_format_keeps_all_columns(self):
        old, new = self.sources(KP_A, KP_B)
        cols, auto = comparable_columns("a", "b", [], old, new)
        self.assertEqual(cols, ["Password", "URL", "Notes", "TOTP", "Icon", "Last Modified", "Created"])
        self.assertEqual(auto, [])

    def test_without_sources_the_core_columns_are_compared(self):
        cols, auto = comparable_columns("a", "b", [], None, None)
        self.assertEqual(len(cols), 7)
        self.assertEqual(auto, [])

    def test_columns_nobody_provides_are_not_reported(self):
        old, new = self.sources(KP_A, KP_B)
        _, auto = comparable_columns("a", "b", [], old, new)
        self.assertNotIn("Favorite", [c for c, _ in auto])


class ExportAcrossFormatsTests(unittest.TestCase):
    def test_merged_export_of_keepass_against_bitwarden(self):
        result = analyze("kp.csv", KP_A, "bw.json", BW_JSON, {"export_merged": True})
        rows = {r["Title"]: r for r in __import__("csv").DictReader(
            result["exports"]["merged"]["csv"].splitlines(keepends=True))}
        self.assertEqual(len(rows), 8 + 1 - 1)       # 8 + Notiz, ohne Papierkorb
        self.assertEqual(rows["WLAN-Zugang"]["Group"], "Privat-DB/Privat")  # Präfix aus der KeePass-Datei
        self.assertEqual(rows["Router"]["Group"], "Privat-DB")
        self.assertEqual(list(rows["Mail"].keys()),
                         ["Group", "Title", "Username", "Password", "URL", "Notes", "TOTP",
                          "Icon", "Last Modified", "Created"])


if __name__ == "__main__":
    unittest.main()
