"""Regressionstests für compare_csv.py.

Die Tests rufen das Skript wie ein Nutzer über die Kommandozeile auf und werten
vorwiegend die JSON-Ausgabe aus. Sie bleiben dadurch gültig, wenn der Code intern
umgebaut oder auf Module verteilt wird.

Ausführen (im Projektverzeichnis):  python3 -m unittest discover -s tests -v
"""
import csv
import json
import os
import tempfile
import unittest

from tests.helpers import fixture_path, run, run_json, titles

ALT = fixture_path("alt.csv")
NEU = fixture_path("neu.csv")
PROBLEME = fixture_path("probleme.csv")
PASSWOERTER = fixture_path("passwoerter.csv")

HEADER = ["Group", "Title", "Username", "Password", "URL", "Notes", "TOTP",
          "Icon", "Last Modified", "Created"]


def write_csv_file(path, rows, header=HEADER, encoding="utf-8"):
    with open(path, "w", newline="", encoding=encoding) as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def read_csv_file(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class CompareTests(unittest.TestCase):
    def test_identical_files_have_no_differences(self):
        rc, r = run_json(ALT, ALT)
        self.assertEqual(rc, 0)
        self.assertTrue(r["summary"]["identical"])
        rc, out, _ = run(ALT, ALT)
        self.assertIn("Keine Unterschiede.", out)

    def test_summary_counts(self):
        _, r = run_json(ALT, NEU)
        self.assertEqual(r["mode"], "compare")
        self.assertEqual(r["summary"], {
            "only_in_old": 2, "only_in_new": 4, "moved": 1, "changed": 5,
            "newer_in_new": 2, "newer_in_old": 1, "unclear": 2, "identical": False,
        })
        self.assertEqual(r["files"]["old"]["entries"], 9)
        self.assertEqual(r["files"]["new"]["entries"], 11)

    def test_changed_entries_are_grouped_by_newer_file(self):
        _, r = run_json(ALT, NEU)
        ch = r["changed"]
        self.assertEqual(titles(i["entry"] for i in ch["newer_in_new"]), ["Forum", "Mail"])
        self.assertEqual(titles(i["entry"] for i in ch["newer_in_old"]), ["Shop"])
        self.assertEqual(titles(i["entry"] for i in ch["unclear"]), ["Blog", "Icon-Test"])

    def test_timestamp_only_change_is_flagged(self):
        _, r = run_json(ALT, NEU)
        forum = next(i for i in r["changed"]["newer_in_new"] if i["entry"]["title"] == "Forum")
        self.assertTrue(forum["only_timestamp"])
        mail = next(i for i in r["changed"]["newer_in_new"] if i["entry"]["title"] == "Mail")
        self.assertFalse(mail["only_timestamp"])
        self.assertEqual(mail["differing_columns"], ["Password", "Last Modified"])

    def test_text_output_uses_real_file_names(self):
        rc, out, _ = run(ALT, NEU)
        self.assertEqual(rc, 0)
        self.assertIn("alt.csv", out)
        self.assertIn("neu.csv", out)
        self.assertNotIn("Datei 1", out)
        self.assertIn("== Verschoben/umbenannt: 1 ==", out)


class MoveDetectionTests(unittest.TestCase):
    def test_moved_entry_is_paired(self):
        _, r = run_json(ALT, NEU)
        self.assertEqual(len(r["moved"]), 1)
        m = r["moved"][0]
        self.assertEqual(m["entry"]["title"], "Streaming")
        self.assertEqual(m["moved_to"]["title"], "Streaming-Abo")
        self.assertEqual(m["changed_key_columns"], ["Group", "Title"])
        self.assertEqual(m["confidence"], "certain")
        self.assertEqual(m["differing_columns"], [])
        self.assertNotIn("Streaming", titles(r["only_in_old"]))
        self.assertNotIn("Streaming-Abo", titles(r["only_in_new"]))

    def test_ambiguous_candidates_are_not_paired(self):
        _, r = run_json(ALT, NEU)
        self.assertIn("Zwilling", titles(r["only_in_old"]))
        self.assertEqual([t for t in titles(r["only_in_new"]) if t.startswith("Zwilling")],
                         ["Zwilling A", "Zwilling B"])

    def test_no_detect_moves_restores_old_behaviour(self):
        _, r = run_json(ALT, NEU, "--no-detect-moves")
        self.assertEqual(r["summary"]["moved"], 0)
        self.assertIn("Streaming", titles(r["only_in_old"]))
        self.assertIn("Streaming-Abo", titles(r["only_in_new"]))

    def test_move_with_different_password_is_not_detected(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
            created = "2023-03-03T08:00:00Z"
            write_csv_file(a, [["Web", "Umbenannt", "max", "pwU", "", "", "", "1",
                                "2024-01-01T10:00:00Z", created]])
            write_csv_file(b, [["Web", "Neuer Name", "max", "pwU-NEU", "", "", "", "1",
                                "2024-06-01T10:00:00Z", created]])
            _, r = run_json(a, b)
            self.assertEqual(r["summary"]["moved"], 0)
            self.assertEqual(titles(r["only_in_old"]), ["Umbenannt"])
            self.assertEqual(titles(r["only_in_new"]), ["Neuer Name"])

    def test_likely_match_without_created(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
            write_csv_file(a, [["Web", "Alt", "max", "pw", "https://x.example.org", "", "", "1",
                                "2024-01-01T10:00:00Z", "2023-01-01T00:00:00Z"]])
            write_csv_file(b, [["Web", "Neu", "max", "pw", "https://x.example.org", "", "", "1",
                                "2024-01-01T10:00:00Z", "2024-02-02T00:00:00Z"]])
            _, r = run_json(a, b)
            self.assertEqual(len(r["moved"]), 1)
            self.assertEqual(r["moved"][0]["confidence"], "likely")


class IgnoreAndFilterTests(unittest.TestCase):
    def test_ignore_column_hides_that_difference(self):
        _, r = run_json(ALT, NEU, "--ignore", "Icon")
        self.assertNotIn("Icon-Test", titles(i["entry"] for i in r["changed"]["unclear"]))
        self.assertEqual(r["filters"]["ignored_columns"], ["Icon"])

    def test_ignore_accepts_commas_and_any_case(self):
        _, r = run_json(ALT, NEU, "--ignore", "icon,notes")
        self.assertEqual(r["filters"]["ignored_columns"], ["Icon", "Notes"])
        self.assertEqual(r["changed"]["unclear"], [])

    def test_ignore_unknown_or_key_column_is_rejected(self):
        rc, _, err = run(ALT, NEU, "--ignore", "Foo")
        self.assertEqual(rc, 2)
        self.assertIn("Unbekannte Spalte", err)
        rc, _, err = run(ALT, NEU, "--ignore", "Title")
        self.assertEqual(rc, 2)
        self.assertIn("kann nicht ignoriert werden", err)

    def test_hide_trash_removes_trash_entries(self):
        _, r = run_json(ALT, NEU)
        self.assertIn("Gelöscht", titles(r["only_in_new"]))
        _, r = run_json(ALT, NEU, "--hide-trash")
        self.assertNotIn("Gelöscht", titles(r["only_in_new"]))
        self.assertEqual(r["files"]["new"]["entries"], 10)
        self.assertTrue(r["filters"]["hide_trash"])

    def test_group_filter(self):
        _, r = run_json(ALT, NEU, "--group", "PRIVAT")
        self.assertEqual(r["files"]["old"]["entries"], 3)
        self.assertEqual(r["files"]["new"]["entries"], 2)
        self.assertEqual(r["filters"]["group"], "PRIVAT")

    def test_empty_group_is_rejected(self):
        rc, _, err = run(ALT, NEU, "--group", " ")
        self.assertEqual(rc, 2)
        self.assertIn("nicht-leeren", err)


class SecretsTests(unittest.TestCase):
    def test_passwords_are_masked_by_default(self):
        rc, out, _ = run(ALT, NEU, "--format", "json")
        self.assertEqual(rc, 0)
        self.assertNotIn("pw-mail", out)
        _, r = run_json(ALT, NEU)
        mail = next(i for i in r["changed"]["newer_in_new"] if i["entry"]["title"] == "Mail")
        self.assertTrue(mail["changes"]["Password"]["masked"])

    def test_show_secrets_reveals_passwords(self):
        _, r = run_json(ALT, NEU, "--show-secrets")
        mail = next(i for i in r["changed"]["newer_in_new"] if i["entry"]["title"] == "Mail")
        self.assertEqual(mail["changes"]["Password"], {"old": "pw-mail-1", "new": "pw-mail-2"})

    def test_text_output_masks_passwords(self):
        _, out, _ = run(ALT, NEU)
        self.assertNotIn("pw-mail", out)
        _, out, _ = run(ALT, NEU, "--show-secrets")
        self.assertIn("pw-mail-1", out)


class SearchTests(unittest.TestCase):
    def test_search_finds_entry_with_status(self):
        rc, r = run_json(ALT, NEU, "--search", "mail")
        self.assertEqual(rc, 0)
        self.assertEqual(r["match_count"], 1)
        self.assertEqual(r["results"][0]["status"], "newer_in_new")

    def test_search_matches_username_group_and_title(self):
        for term in ("max@example.org", "privat", "bank"):
            _, r = run_json(ALT, NEU, "--search", term)
            self.assertGreaterEqual(r["match_count"], 1, term)

    def test_search_reports_moved_pair_once(self):
        _, r = run_json(ALT, NEU, "--search", "streaming")
        self.assertEqual([x["status"] for x in r["results"]], ["moved"])
        self.assertEqual(r["match_count"], 1)   # ein Paar ist ein Treffer, nicht zwei
        _, out, _ = run(ALT, NEU, "--search", "streaming")
        self.assertIn("1 Treffer", out)

    def test_search_statuses(self):
        _, r = run_json(ALT, NEU, "--search", "bank")
        self.assertEqual(r["results"][0]["status"], "identical")
        _, r = run_json(ALT, NEU, "--search", "neuer-account")
        self.assertEqual(r["results"][0]["status"], "only_in_new")
        _, r = run_json(ALT, NEU, "--search", "alt-account")
        self.assertEqual(r["results"][0]["status"], "only_in_old")

    def test_search_without_match_exits_with_one(self):
        rc, r = run_json(ALT, NEU, "--search", "zzz")
        self.assertEqual(rc, 1)
        self.assertEqual(r["match_count"], 0)
        rc, _, err = run(ALT, NEU, "--search", "zzz")
        self.assertEqual(rc, 1)
        self.assertIn("Kein Eintrag gefunden", err)

    def test_search_is_incompatible_with_exports_and_other_modes(self):
        for extra in (["--export-added"], ["--export-merged"], ["--stats"], ["--check"],
                      ["--password-check"]):
            rc, _, err = run(ALT, NEU, "--search", "mail", *extra)
            self.assertEqual(rc, 2, extra)
            self.assertIn("können nicht kombiniert werden", err)


class ModeTests(unittest.TestCase):
    def test_stats(self):
        _, r = run_json(ALT, NEU, "--stats")
        self.assertEqual(r["mode"], "stats")
        by_group = {g["group"]: (g["old"], g["new"], g["difference"]) for g in r["groups"]}
        self.assertEqual(by_group, {"Papierkorb": (0, 1, 1), "Privat": (3, 2, -1),
                                    "Web": (6, 8, 2)})
        self.assertEqual(r["total"], {"old": 9, "new": 11, "difference": 2})

    def test_check_finds_all_problem_categories(self):
        _, r = run_json(PROBLEME, ALT, "--check")
        findings = {f["category"]: f["count"] for f in r["results"][0]["findings"]}
        self.assertEqual(findings, {
            "Doppelte Einträge (gleiche Gruppe, Titel und Username)": 1,
            "Gleicher Titel und Username in verschiedenen Gruppen": 1,
            "Gleiche URL und Username in verschiedenen Einträgen": 1,
            "Einträge ohne Passwort": 1,
            "Einträge ohne Titel": 1,
            "Ungültige URLs": 2,
        })
        self.assertEqual(r["results"][1]["findings"], [])

    def test_check_accepts_localhost_ip_and_schemeless_urls(self):
        _, r = run_json(PROBLEME, ALT, "--check")
        urls = next(f for f in r["results"][0]["findings"] if f["category"] == "Ungültige URLs")
        text = " ".join(urls["items"])
        self.assertIn("kaputt url", text)
        self.assertIn("intranet", text)
        for ok in ("localhost", "192.168.0.1", "example.org"):
            self.assertNotIn(f"'{ok}'", text)

    def test_password_check_findings_and_no_leaks(self):
        rc, out, _ = run(PASSWOERTER, ALT, "--password-check", "--format", "json",
                         "--max-age-days", "100000")
        self.assertEqual(rc, 0)
        for secret in ("Sehr-langes", "gleiches-Passwort", "abc123", "Noch-ein"):
            self.assertNotIn(secret, out)
        r = json.loads(out)
        res = r["results"][0]
        cats = {f["category"]: f["count"] for f in res["findings"]}
        self.assertEqual(cats, {"Wiederverwendete Passwörter": 1,
                                "Kurze Passwörter (< 10 Zeichen)": 1})
        self.assertEqual(res["totp"], {"with_totp": 1, "entries": 6})
        self.assertEqual(r["thresholds"], {"min_length": 10, "max_age_days": 100000})

    def test_password_check_thresholds_are_configurable(self):
        _, r = run_json(PASSWOERTER, ALT, "--password-check", "--min-length", "25",
                        "--max-age-days", "100000")
        cats = {f["category"]: f["count"] for f in r["results"][0]["findings"]}
        self.assertEqual(cats["Kurze Passwörter (< 25 Zeichen)"], 5)

    def test_password_check_flags_old_entries(self):
        _, r = run_json(PASSWOERTER, ALT, "--password-check")
        cats = [f["category"] for f in r["results"][0]["findings"]]
        self.assertIn("Lange nicht geändert (> 730 Tage)", cats)

    def test_modes_are_mutually_exclusive(self):
        for args in (["--stats", "--check"], ["--check", "--password-check"],
                     ["--stats", "--export-added"], ["--check", "--export-merged"],
                     ["--password-check", "--export-added"]):
            rc, _, err = run(ALT, NEU, *args)
            self.assertEqual(rc, 2, args)
            self.assertIn("können nicht kombiniert werden", err)

    def test_modes_respect_filters(self):
        _, r = run_json(ALT, NEU, "--stats", "--hide-trash", "-g", "web")
        self.assertEqual([g["group"] for g in r["groups"]], ["Web"])


class ExportTests(unittest.TestCase):
    def test_export_added_excludes_trash_and_moved_entries(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "added.csv")
            rc, stdout, _ = run(ALT, NEU, "--export-added", out)
            self.assertEqual(rc, 0)
            self.assertIn("1 aus Papierkorb ausgelassen", stdout)
            rows = read_csv_file(out)
            self.assertEqual(sorted(r["Title"] for r in rows),
                             ["Neuer-Account", "Zwilling A", "Zwilling B"])
            with open(out, newline="", encoding="utf-8") as f:
                self.assertEqual(next(csv.reader(f)), HEADER)

    def test_export_merged_takes_newer_version(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "merged.csv")
            rc, stdout, _ = run(ALT, NEU, "--export-merged", out)
            self.assertEqual(rc, 0)
            self.assertIn("2 Konflikt(e)", stdout)
            rows = {r["Title"]: r for r in read_csv_file(out)}
            self.assertEqual(len(rows), 12)
            self.assertNotIn("Gelöscht", rows)
            self.assertEqual(rows["Mail"]["Password"], "pw-mail-2")      # neu.csv ist neuer
            self.assertEqual(rows["Shop"]["Notes"], "Zeile 1\nZeile 2")  # alt.csv ist neuer
            self.assertEqual(rows["Forum"]["Last Modified"], "2024-02-01T10:00:00Z")
            self.assertIn("Streaming-Abo", rows)
            self.assertNotIn("Streaming", rows)
            # Konflikte: Version aus der zweiten Datei
            self.assertEqual(rows["Icon-Test"]["Icon"], "9")
            self.assertEqual(rows["Blog"]["Notes"], "neue Notiz")

    def test_export_merged_of_identical_files_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "merged.csv")
            run(ALT, ALT, "--export-merged", out)
            self.assertEqual(len(read_csv_file(out)), 9)

    def test_json_stdout_stays_valid_when_exporting(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = run(ALT, NEU, "--format", "json",
                               "--export-added", os.path.join(d, "a.csv"),
                               "--export-merged", os.path.join(d, "m.csv"))
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out)["mode"], "compare")
            self.assertIn("exportiert", err)
            self.assertTrue(os.path.exists(os.path.join(d, "a.csv")))

    def test_export_to_unwritable_path_fails_cleanly(self):
        rc, _, err = run(ALT, NEU, "--export-added", "/nonexistent-dir/x.csv")
        self.assertEqual(rc, 1)
        self.assertIn("kann nicht geschrieben werden", err)


class InputTests(unittest.TestCase):
    def test_missing_file(self):
        rc, _, err = run(ALT, "/does/not/exist.csv")
        self.assertEqual(rc, 1)
        self.assertIn("kann nicht gelesen werden", err)

    def test_file_that_is_not_utf8_gives_a_message_instead_of_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            latin1 = os.path.join(d, "latin1.csv")
            with open(latin1, "wb") as f:
                f.write(b"Group,Title\n\xe4\xf6\xfc\n")
            rc, _, err = run(latin1, ALT)
        self.assertEqual(rc, 1)
        self.assertIn("keine UTF-8-Textdatei", err)
        self.assertNotIn("Traceback", err)

    def test_missing_columns(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.csv")
            write_csv_file(bad, [["a", "b"]], header=["Group", "Title"])
            rc, _, err = run(ALT, bad)
            self.assertEqual(rc, 1)
            self.assertIn("fehlen Spalten", err)

    def test_utf8_bom_and_umlauts(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
            row = ["Büro", "Größe", "ü@example.org", "pw", "", "", "", "1",
                   "2024-01-01T10:00:00Z", "2023-01-01T00:00:00Z"]
            write_csv_file(a, [row], encoding="utf-8-sig")
            write_csv_file(b, [row], encoding="utf-8")
            _, r = run_json(a, b)
            self.assertTrue(r["summary"]["identical"])
            self.assertEqual(r["files"]["old"]["entries"], 1)

    def test_same_file_name_in_different_folders_shows_paths(self):
        with tempfile.TemporaryDirectory() as d:
            sub1, sub2 = os.path.join(d, "eins"), os.path.join(d, "zwei")
            os.makedirs(sub1)
            os.makedirs(sub2)
            row = ["Web", "X", "u", "pw", "", "", "", "1",
                   "2024-01-01T10:00:00Z", "2023-01-01T00:00:00Z"]
            a, b = os.path.join(sub1, "export.csv"), os.path.join(sub2, "export.csv")
            write_csv_file(a, [row])
            write_csv_file(b, [row])
            _, r = run_json(a, b)
            self.assertEqual(r["files"]["old"]["name"], a)
            self.assertEqual(r["files"]["new"]["name"], b)

    def test_duplicate_keys_are_kept_apart(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.csv"), os.path.join(d, "b.csv")
            r1 = ["Web", "Dup", "u", "pw1", "", "", "", "1", "2024-01-01T10:00:00Z", "c1"]
            r2 = ["Web", "Dup", "u", "pw2", "", "", "", "1", "2024-01-01T10:00:00Z", "c2"]
            write_csv_file(a, [r1, r2])
            write_csv_file(b, [r1])
            _, r = run_json(a, b)
            self.assertEqual(r["files"]["old"]["entries"], 2)
            self.assertEqual(len(r["only_in_old"]), 1)
            self.assertEqual(r["only_in_old"][0]["duplicate_index"], 2)


if __name__ == "__main__":
    unittest.main()
