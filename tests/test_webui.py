"""Tests des lokalen Webservers: Verhalten und Schutzmaßnahmen."""

import http.client
import json
import os
import subprocess
import sys
import threading
import unittest

from csvcompare.service import analyze
from csvcompare.webui import make_server
from tests.helpers import ROOT, read_fixture

ALT, NEU = read_fixture("alt.csv"), read_fixture("neu.csv")
TOKEN = "test-token"


class ServerTestCase(unittest.TestCase):
    max_body = 64 * 1024 * 1024

    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0, token=TOKEN, max_body=cls.max_body)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def post(self, payload, token=TOKEN, content_type="application/json", host=None, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["X-Token"] = token
        if host is not None:
            headers["Host"] = host
        return self.request("POST", "/api/analyze", body, headers)

    @staticmethod
    def payload(options=None):
        return {
            "old": {"name": "alt.csv", "text": ALT},
            "new": {"name": "neu.csv", "text": NEU},
            "options": options or {},
        }


class ServerTests(ServerTestCase):
    def test_binds_only_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_index_contains_token_and_security_headers(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(TOKEN, body.decode("utf-8"))
        self.assertNotIn("__TOKEN__", body.decode("utf-8"))
        self.assertIn("default-src 'none'", headers["content-security-policy"])
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertTrue(headers["content-type"].startswith("text/html"))

    def test_unknown_paths(self):
        self.assertEqual(self.request("GET", "/etc/passwd")[0], 404)
        self.assertEqual(self.request("GET", "/api/analyze")[0], 404)
        self.assertEqual(self.request("POST", "/other", b"{}", {"X-Token": TOKEN})[0], 404)

    def test_analyze_returns_same_result_as_service(self):
        status, headers, body = self.post(self.payload({"ignore": ["Icon"], "export_added": True}))
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        expected = analyze(
            "alt.csv", ALT, "neu.csv", NEU, {"ignore": ["Icon"], "export_added": True}
        )
        self.assertEqual(json.loads(body), expected)

    def test_usage_errors_are_reported_as_400_with_message(self):
        status, _, body = self.post(self.payload({"ignore": ["Foo"]}))
        self.assertEqual(status, 400)
        self.assertIn("Unbekannte Spalte", json.loads(body)["error"])

    def test_unusable_csv_is_a_400(self):
        payload = self.payload()
        payload["old"]["text"] = "Group,Title\nx,y\n"
        status, _, body = self.post(payload)
        self.assertEqual(status, 400)
        self.assertIn("fehlen Spalten", json.loads(body)["error"])

    def test_malformed_requests(self):
        for raw in (
            b"not json",
            b"{}",
            b'{"old": 1, "new": 2}',
            json.dumps(
                {"old": {"name": "a", "text": 1}, "new": {"name": "b", "text": ""}}
            ).encode(),
            json.dumps({**self.payload(), "options": []}).encode(),
        ):
            with self.subTest(raw=raw[:30]):
                status, _, _ = self.post(None, raw=raw)
                self.assertEqual(status, 400)

    def test_wrong_content_type(self):
        status, _, _ = self.post(self.payload(), content_type="text/plain")
        self.assertEqual(status, 415)

    def test_search_without_match_is_still_a_normal_answer(self):
        status, _, body = self.post(self.payload({"mode": "search", "search": "zzz"}))
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], 1)
        self.assertEqual(data["report"]["match_count"], 0)


class FormatTests(ServerTestCase):
    def test_json_and_csv_exports_can_be_compared(self):
        payload = {
            "old": {"name": "kp.csv", "text": read_fixture("keepassium_a.csv")},
            "new": {"name": "bw.json", "text": read_fixture("bitwarden.json")},
            "options": {},
        }
        status, _, body = self.post(payload)
        self.assertEqual(status, 200)
        files = json.loads(body)["report"]["files"]
        self.assertEqual(
            (files["old"]["format"], files["new"]["format"]), ("keepass-csv", "bitwarden-json")
        )
        self.assertTrue(files["new"]["notes"])

    def test_encrypted_bitwarden_export_is_a_clear_400(self):
        payload = {
            "old": {"name": "a.json", "text": json.dumps({"encrypted": True, "data": "x"})},
            "new": {"name": "b.csv", "text": read_fixture("keepassium_a.csv")},
            "options": {},
        }
        status, _, body = self.post(payload)
        self.assertEqual(status, 400)
        self.assertIn("verschlüsselter Bitwarden-Export", json.loads(body)["error"])


class SecurityTests(ServerTestCase):
    def test_missing_or_wrong_token_is_rejected(self):
        for token in (None, "", "falsch", TOKEN + "x"):
            with self.subTest(token=token):
                status, _, body = self.post(self.payload(), token=token)
                self.assertEqual(status, 403)
                self.assertNotIn("Eintrag", body.decode("utf-8"))

    def test_foreign_host_header_is_rejected(self):
        for host in (
            "evil.example.com",
            "evil.example.com:80",
            "192.168.1.5:8765",
            "127.0.0.1.evil.com",
        ):
            with self.subTest(host=host):
                self.assertEqual(self.post(self.payload(), host=host)[0], 403)
                self.assertEqual(self.request("GET", "/", headers={"Host": host})[0], 403)

    def test_localhost_host_header_is_accepted(self):
        for host in ("localhost", f"localhost:{self.port}", f"127.0.0.1:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.request("GET", "/", headers={"Host": host})[0], 200)

    def test_token_is_random_per_server(self):
        other = make_server(0)
        try:
            self.assertNotEqual(other.token, TOKEN)
            self.assertGreaterEqual(len(other.token), 24)
        finally:
            other.server_close()

    def test_no_cors_headers(self):
        _, headers, _ = self.post(self.payload())
        self.assertNotIn("access-control-allow-origin", headers)

    def test_server_does_not_log_requests(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, {ROOT!r}); "
                "from csvcompare.webui import make_handler; "
                "h = make_handler('t', 1); print(h.log_message.__qualname__)",
            ],
            capture_output=True,
            text=True,
        )
        self.assertIn("log_message", proc.stdout)
        self.assertEqual(proc.stderr, "")


class SmallLimitTests(ServerTestCase):
    max_body = 2000

    def test_oversized_body_is_rejected(self):
        status, _, body = self.post(self.payload())  # größer als 2000 Bytes
        self.assertEqual(status, 413)
        self.assertIn("zu groß", json.loads(body)["error"])

    def test_missing_content_length_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/analyze")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("X-Token", TOKEN)
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 411)
        finally:
            conn.close()


class StaticPageTests(unittest.TestCase):
    """Die Oberfläche darf nichts nachladen und Dateiinhalte nie als HTML einsetzen."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "csvcompare", "web", "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_token_placeholder_appears_once(self):
        self.assertEqual(self.html.count("__TOKEN__"), 1)

    def test_page_loads_nothing_from_outside(self):
        import re

        self.assertEqual(re.findall(r"https?://", self.html), [])
        self.assertEqual(re.findall(r"""\b(?:src|href)\s*=\s*["'](?!#)""", self.html), [])
        self.assertNotIn("@import", self.html)
        self.assertNotIn("url(", self.html)

    def test_file_contents_are_never_inserted_as_html(self):
        for risky in (
            "innerHTML",
            "outerHTML",
            "insertAdjacentHTML",
            "document.write",
            "eval(",
            "new Function",
            "srcdoc",
        ):
            self.assertNotIn(risky, self.html, risky)

    def test_page_does_not_store_anything_in_the_browser(self):
        for storage in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
            self.assertNotIn(storage, self.html, storage)

    def test_page_accepts_json_files_and_knows_the_new_columns(self):
        self.assertEqual(self.html.count('accept=".csv,.json,'), 2)
        for column in ("Favorite", "Type", "Reprompt", "Fields", "URLs"):
            self.assertIn(f'"{column}"', self.html)
        self.assertIn('id="keep-db-name"', self.html)
        self.assertIn("keep_db_name", self.html)

    def test_page_offers_both_export_formats_and_sends_the_choice(self):
        from csvcompare.writers import WRITERS

        for format_id in WRITERS:
            self.assertIn(f'name="export-format" value="{format_id}"', self.html)
        self.assertIn("opts.export_format = exportFormat()", self.html)
        self.assertIn("e.mime", self.html)  # Download mit dem Medientyp des Formats

    def test_format_detection_in_the_page_matches_the_server(self):
        import re
        import shutil

        node = shutil.which("node")
        if not node:
            self.skipTest("node ist nicht installiert")
        from csvcompare.importers import load_any

        func = re.search(r"function sniffFormat\(text\) \{.*?\n\}", self.html, re.S).group(0)
        samples = {
            name: read_fixture(name)
            for name in ("alt.csv", "keepassium_a.csv", "bitwarden.json", "bitwarden.csv")
        }
        samples["bom.json"] = chr(0xFEFF) + samples["bitwarden.json"]
        samples["bom.csv"] = chr(0xFEFF) + samples["bitwarden.csv"]
        samples["blank.json"] = "\n  " + samples["bitwarden.json"]
        samples["crlf.csv"] = samples["bitwarden.csv"].replace("\n", "\r\n")
        script = (
            func + "\nconst s = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
            "console.log(JSON.stringify(Object.fromEntries("
            "Object.entries(s).map(([k, v]) => [k, sniffFormat(v)]))));"
        )
        proc = subprocess.run(
            [node, "-e", script],
            input=json.dumps(samples),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        in_page = json.loads(proc.stdout)
        for name, text in samples.items():
            with self.subTest(name=name):
                self.assertEqual(in_page[name], load_any(name, text).format)

    def test_downloads_have_no_byte_order_mark(self):
        # Die CSV-Downloads müssen byte-gleich zu den Dateien aus dem Terminal sein.
        self.assertNotIn(chr(0xFEFF), self.html)

    def test_javascript_syntax(self):
        import re
        import shutil
        import tempfile

        node = shutil.which("node")
        if not node:
            self.skipTest("node ist nicht installiert")
        js = re.search(r"<script>(.*?)</script>", self.html, re.S).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
            f.write(js)
        try:
            proc = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        finally:
            os.unlink(f.name)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class CommandLineEntryTests(unittest.TestCase):
    def test_ui_rejects_files(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "compare_csv.py"), "--ui", "tests/alt.csv"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--ui braucht keine Dateien", proc.stderr)

    def test_files_are_still_required_without_ui(self):
        for args in ([], ["tests/alt.csv"]):
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "compare_csv.py"), *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("required: alt, neu", proc.stderr)

    def test_ui_starts_and_serves_on_loopback(self):
        proc = subprocess.Popen(
            [
                sys.executable,
                os.path.join(ROOT, "compare_csv.py"),
                "--ui",
                "--no-browser",
                "--port",
                "0",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = proc.stdout.readline()
            self.assertIn("http://127.0.0.1:", line)
            port = int(line.rsplit(":", 1)[1].strip("/\n "))
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/")
            self.assertEqual(conn.getresponse().status, 200)
            conn.close()
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
            proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
