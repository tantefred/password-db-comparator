"""Tests des Bitwarden-JSON-Writers: Aufbau, Erhalt von Originaldaten und Round-Trip."""

import copy
import json
import unittest

from csvcompare.columns import SOURCE_KEY
from csvcompare.importers import load_any
from csvcompare.service import analyze
from csvcompare.writers import BITWARDEN_JSON_WRITER, WRITERS, lost_data
from csvcompare.writers.bitwarden_json import parse_fields
from tests.helpers import read_fixture

W = BITWARDEN_JSON_WRITER
BW_JSON, BW_CSV = read_fixture("bitwarden.json"), read_fixture("bitwarden.csv")
KP_A = read_fixture("keepassium_a.csv")
DATA = json.loads(BW_JSON)


def rows_of(name, text, drop_trash=False):
    rows = load_any(name, text).rows
    if drop_trash:
        rows = [r for r in rows if r["Group"] != "Papierkorb"]
    return rows


def export(name, text, drop_trash=False):
    return W.data(rows_of(name, text, drop_trash))


def item_named(data, name):
    return next(i for i in data["items"] if i["name"] == name)


def folder_name(data, item):
    return next((f["name"] for f in data["folders"] if f["id"] == item["folderId"]), None)


class StructureTests(unittest.TestCase):
    def test_registered_with_the_json_extension_and_mime_type(self):
        self.assertIs(WRITERS["bitwarden-json"], W)
        self.assertEqual((W.extension, W.mime), (".json", "application/json"))
        self.assertFalse(W.prefix_groups)

    def test_top_level_layout(self):
        data = export("kp.csv", KP_A)
        self.assertEqual(list(data), ["encrypted", "folders", "items"])
        self.assertIs(data["encrypted"], False)
        self.assertEqual(len(data["items"]), 8)

    def test_folders_are_the_distinct_groups_and_entries_link_to_them(self):
        data = export("kp.csv", KP_A)
        names = [f["name"] for f in data["folders"]]
        self.assertEqual(names, ["Papierkorb", "Privat", "Web", "Web/Shops"])
        self.assertEqual(len({f["id"] for f in data["folders"]}), len(names))
        self.assertEqual(folder_name(data, item_named(data, "Shop")), "Web/Shops")
        self.assertIsNone(item_named(data, "Router")["folderId"])  # liegt in der Wurzel

    def test_new_items_use_the_key_order_bitwarden_writes(self):
        item = export("kp.csv", KP_A)["items"][0]
        self.assertEqual(
            list(item)[:6],
            [
                "passwordHistory",
                "revisionDate",
                "creationDate",
                "deletedDate",
                "id",
                "organizationId",
            ],
        )
        self.assertEqual(list(item)[-2:], ["login", "collectionIds"])

    def test_empty_export_is_valid(self):
        text = W.text([])
        self.assertEqual(json.loads(text), {"encrypted": False, "folders": [], "items": []})
        self.assertTrue(text.endswith("\n"))

    def test_output_is_deterministic(self):
        rows = rows_of("kp.csv", KP_A)
        self.assertEqual(W.text(rows), W.text(copy.deepcopy(rows)))

    def test_ids_are_unique_even_for_identical_entries(self):
        row = rows_of("kp.csv", KP_A)[0]
        data = W.data([dict(row), dict(row), dict(row)])
        self.assertEqual(len({i["id"] for i in data["items"]}), 3)


class KeePassRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = export("kp.csv", KP_A)

    def test_login_is_built_from_the_columns(self):
        mail = item_named(self.data, "Mail")
        self.assertEqual(mail["type"], 1)
        self.assertEqual(
            mail["login"],
            {
                "fido2Credentials": [],
                "uris": [{"match": None, "uri": "https://mail.example.org"}],
                "username": "max@example.org",
                "password": "pw-mail-1",
                "totp": "JBSWY3DPEHPK3PXP",
            },
        )

    def test_empty_values_become_null(self):
        mail = item_named(self.data, "Mail")
        self.assertIsNone(mail["notes"])
        self.assertIsNone(mail["fields"])
        alt = item_named(self.data, "Alt-Account")
        self.assertEqual(alt["login"]["uris"], [])
        self.assertIsNone(alt["login"]["totp"])

    def test_times_use_the_bitwarden_notation(self):
        mail = item_named(self.data, "Mail")
        self.assertEqual(mail["revisionDate"], "2024-01-10T10:00:00.000Z")
        self.assertEqual(mail["creationDate"], "2023-01-01T09:00:00.000Z")

    def test_missing_or_unreadable_times_become_null(self):
        row = dict(rows_of("kp.csv", KP_A)[0], **{"Last Modified": "", "Created": "irgendwann"})
        item = W.data([row])["items"][0]
        self.assertIsNone(item["revisionDate"])
        self.assertIsNone(item["creationDate"])

    def test_multiline_notes_survive(self):
        self.assertEqual(item_named(self.data, "Shop")["notes"], "Zeile 1\nZeile 2")

    def test_the_icon_is_the_only_lost_column(self):
        lost = lost_data(rows_of("kp.csv", KP_A), W)
        self.assertEqual(lost, {"columns": {"Icon": 8}, "source": {}})


class BitwardenJsonRowsTests(unittest.TestCase):
    def test_every_original_item_comes_back_unchanged(self):
        data = export("bw.json", BW_JSON, drop_trash=True)
        originals = {i["id"]: i for i in DATA["items"] if i["type"] in (1, 2)}
        self.assertEqual(len(data["items"]), 8)
        for item in data["items"]:
            original = copy.deepcopy(originals[item["id"]])
            self.assertEqual(folder_name(data, item), self.folder_of(original), item["name"])
            original["folderId"] = item["folderId"]  # die Ordner-IDs sind neu
            self.assertEqual(item, original, item["name"])

    @staticmethod
    def folder_of(item):
        return next((f["name"] for f in DATA["folders"] if f["id"] == item["folderId"]), None)

    def test_same_ids_keys_and_order_of_keys(self):
        data = export("bw.json", BW_JSON, drop_trash=True)
        original = next(i for i in DATA["items"] if i["name"] == "Mail")
        self.assertEqual(list(item_named(data, "Mail")), list(original))

    def test_nothing_is_lost(self):
        lost = lost_data(rows_of("bw.json", BW_JSON, drop_trash=True), W)
        self.assertEqual(lost, {"columns": {}, "source": {}})

    def test_edited_columns_overlay_the_original_and_keep_the_rest(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        mail = next(r for r in rows if r["Title"] == "Mail")
        mail["Password"] = "neues-passwort"
        mail["Last Modified"] = "2025-03-04T05:06:07Z"
        item = item_named(W.data(rows), "Mail")
        self.assertEqual(item["login"]["password"], "neues-passwort")
        self.assertEqual(item["revisionDate"], "2025-03-04T05:06:07.000Z")
        self.assertEqual(item["passwordHistory"][0]["password"], "pw-mail-0")
        self.assertEqual(
            item["fields"][0], {"name": "PIN", "value": "1234", "type": 1, "linkedId": None}
        )
        self.assertEqual(item["id"], "0001")

    def test_changed_urls_replace_the_original_ones(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        shop = next(r for r in rows if r["Title"] == "Shop")
        shop["URLs"] = "https://neu.example.org"
        shop["URL"] = "https://neu.example.org"
        self.assertEqual(
            item_named(W.data(rows), "Shop")["login"]["uris"],
            [{"match": None, "uri": "https://neu.example.org"}],
        )

    def test_changed_fields_are_rebuilt_from_the_column(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        mail = next(r for r in rows if r["Title"] == "Mail")
        mail["Fields"] = "PIN: 9999"
        fields = item_named(W.data(rows), "Mail")["fields"]
        self.assertEqual([(f["name"], f["value"]) for f in fields], [("PIN", "9999")])

    def test_secure_note(self):
        item = item_named(export("bw.json", BW_JSON, drop_trash=True), "WLAN-Zugang")
        self.assertEqual(item["type"], 2)
        self.assertNotIn("login", item)
        self.assertEqual(item["secureNote"], {"type": 0})
        self.assertEqual(item["notes"], "SSID: Heimnetz")

    def test_a_login_turned_into_a_note_and_back(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        forum = next(r for r in rows if r["Title"] == "Forum")
        forum["Type"] = "note"
        item = item_named(W.data(rows), "Forum")
        self.assertEqual(
            (item["type"], "login" in item, item["secureNote"]), (2, False, {"type": 0})
        )

    def test_duplicate_source_ids_get_new_unique_ids(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        rows[1][SOURCE_KEY]["id"] = rows[0][SOURCE_KEY]["id"]
        ids = [i["id"] for i in W.data(rows)["items"]]
        self.assertEqual(len(set(ids)), len(ids))


class BitwardenCsvRowsTests(unittest.TestCase):
    def test_newline_separated_fields_are_exact(self):
        fields, exact = parse_fields("PIN: 1234\nKonto: Haupt konto")
        self.assertTrue(exact)
        self.assertEqual(
            [(f["name"], f["value"]) for f in fields], [("PIN", "1234"), ("Konto", "Haupt konto")]
        )

    def test_space_separated_fields_are_a_guess(self):
        fields, exact = parse_fields("PIN: 1234 Konto: Haupt konto")
        self.assertFalse(exact)
        self.assertEqual(
            [(f["name"], f["value"]) for f in fields], [("PIN", "1234"), ("Konto", "Haupt konto")]
        )

    def test_fields_edge_cases(self):
        self.assertEqual(parse_fields("")[0], [])
        self.assertEqual(parse_fields("ohne doppelpunkt")[0], [])
        self.assertEqual(parse_fields("Name:")[0][0]["value"], "")

    def test_guessed_fields_are_reported(self):
        rows = rows_of("bw.csv", BW_CSV)
        self.assertEqual(len(W.notes(rows)), 1)
        self.assertIn("1 Eintrag", W.notes(rows)[0])
        self.assertIn("nur geschätzt", W.notes(rows)[0])

    def test_exact_fields_need_no_hint(self):
        text = BW_CSV.replace("PIN: 1234 Konto: Haupt konto", '"PIN: 1234\nKonto: Haupt konto"')
        self.assertEqual(W.notes(rows_of("bw.csv", text)), [])

    def test_other_formats_need_no_hint(self):
        self.assertEqual(W.notes(rows_of("bw.json", BW_JSON)), [])
        self.assertEqual(W.notes(rows_of("kp.csv", KP_A)), [])

    def test_extra_csv_columns_cannot_be_restored(self):
        text = BW_CSV.replace("folder,", "collections,folder,", 1)
        lines = text.splitlines(keepends=True)
        lines[1] = "Team," + lines[1]
        lines[2:] = ["," + line for line in lines[2:]]
        lost = lost_data(rows_of("org.csv", "".join(lines)), W)
        self.assertEqual(lost["source"], {"Spalte „collections“": 1})

    def test_urls_are_split_into_uris(self):
        item = item_named(export("bw.csv", BW_CSV), "Shop")
        self.assertEqual(
            [u["uri"] for u in item["login"]["uris"]],
            ["https://shop.example.org", "https://shop.example.org/login"],
        )


class RoundTripTests(unittest.TestCase):
    """Was geschrieben wird, muss der eigene Importer wieder genauso lesen."""

    @staticmethod
    def compare(old_name, old_text, rows):
        return analyze(old_name, old_text, "export.json", W.text(rows), {})["report"]

    def test_bitwarden_json_is_identical_after_a_round_trip(self):
        rows = rows_of("bw.json", BW_JSON, drop_trash=True)
        report = self.compare(
            "bw.json",
            json.dumps(
                {
                    **DATA,
                    "items": [
                        i for i in DATA["items"] if i["type"] in (1, 2) and not i.get("deletedDate")
                    ],
                }
            ),
            rows,
        )
        self.assertTrue(report["summary"]["identical"], report["summary"])

    def test_keepass_csv_is_identical_after_a_round_trip(self):
        report = self.compare("kp.csv", KP_A, rows_of("kp.csv", KP_A))
        self.assertTrue(report["summary"]["identical"], report["summary"])

    def test_bitwarden_csv_is_identical_after_a_round_trip(self):
        report = self.compare("bw.csv", BW_CSV, rows_of("bw.csv", BW_CSV))
        self.assertTrue(report["summary"]["identical"], report["summary"])

    def test_rows_read_back_have_the_same_values(self):
        rows = rows_of("kp.csv", KP_A)
        back = load_any("export.json", W.text(rows)).rows
        columns = [
            "Group",
            "Title",
            "Username",
            "Password",
            "URL",
            "Notes",
            "TOTP",
            "Last Modified",
            "Created",
        ]
        self.assertEqual(
            [[r[c] for c in columns] for r in back], [[r[c] for c in columns] for r in rows]
        )

    def test_output_is_importable_json_without_unknown_top_level_keys(self):
        parsed = json.loads(W.text(rows_of("kp.csv", KP_A)))
        self.assertEqual(set(parsed), {"encrypted", "folders", "items"})


if __name__ == "__main__":
    unittest.main()
