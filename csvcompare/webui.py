"""Lokale Weboberfläche: ein kleiner HTTP-Server, der nur auf diesem Rechner erreichbar ist.

Die CSV-Dateien werden vom Browser an den Server auf 127.0.0.1 geschickt und dort mit
derselben Logik wie im Terminal ausgewertet. Es wird nichts gespeichert und nichts an
andere Rechner gesendet.
"""

import hmac
import json
import os
import secrets
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import UsageError, analyze

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024 * 1024  # 64 MiB reichen für sehr große Passwortdatenbanken
INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")

CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def load_index(token):
    with open(INDEX_PATH, encoding="utf-8") as f:
        return f.read().replace("__TOKEN__", token)


def make_handler(token, max_body, index_loader=load_index):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CsvComparator"
        sys_version = ""

        # --- Hilfen ---------------------------------------------------------
        def log_message(self, *args):  # kein Access-Log: es soll nichts mitgeschrieben werden
            pass

        def _send(self, status, body=b"", content_type="text/plain; charset=utf-8", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _host_ok(self):
            """Nur Anfragen an den eigenen Rechner zulassen (Schutz vor DNS-Rebinding)."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ("127.0.0.1", "localhost", "::1")

        # --- Anfragen ---------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden")
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(
                    200,
                    index_loader(token).encode("utf-8"),
                    "text/html; charset=utf-8",
                    {"Content-Security-Policy": CSP},
                )
            if path == "/favicon.ico":
                return self._send(204)
            self._send(404, b"Not found")

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"Forbidden")
            if self.path.split("?", 1)[0] != "/api/analyze":
                return self._send(404, b"Not found")
            if not hmac.compare_digest(self.headers.get("X-Token", ""), token):
                return self._json(403, {"error": "Ungültiges Sitzungs-Token. Lade die Seite neu."})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._json(415, {"error": "Erwartet application/json."})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._json(411, {"error": "Content-Length fehlt."})
            if length < 0 or length > max_body:
                return self._json(413, {"error": "Die Dateien sind zu groß."})
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
                old, new, options = data["old"], data.get("new"), data.get("options", {})
                names_texts = [old["name"], old["text"]]
                if new is not None:  # die zweite Datei ist optional
                    names_texts += [new["name"], new["text"]]
                if not all(isinstance(x, str) for x in names_texts) or not isinstance(
                    options, dict
                ):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                return self._json(400, {"error": "Ungültige Anfrage."})
            try:
                result = analyze(
                    old["name"],
                    old["text"],
                    new["name"] if new else None,
                    new["text"] if new else None,
                    options,
                )
            except UsageError as e:
                return self._json(400, {"error": str(e)})
            except Exception:  # Fehlerdetails nur auf der Konsole, nie mit Dateiinhalten
                traceback.print_exc(file=sys.stderr)
                return self._json(500, {"error": "Interner Fehler bei der Auswertung."})
            self._json(200, result)

    return Handler


def make_server(
    port=DEFAULT_PORT, token=None, max_body=MAX_BODY, tries=20, index_loader=load_index
):
    """Erzeugt den Server (noch nicht gestartet). Probiert bei belegtem Port die nächsten."""
    token = token or secrets.token_urlsafe(24)
    last_error = None
    for candidate in [port] if port == 0 else range(port, port + tries):
        try:
            server = ThreadingHTTPServer(
                (HOST, candidate), make_handler(token, max_body, index_loader)
            )
        except OSError as e:
            last_error = e
            continue
        server.daemon_threads = True
        server.token = token
        return server
    raise OSError(f"Kein freier Port ab {port} gefunden: {last_error}")


def serve(port=DEFAULT_PORT, open_browser=True):
    """Startet die Oberfläche und blockiert bis zum Beenden mit Strg+C."""
    server = make_server(port)
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"CSV Comparator läuft unter {url}")
    print("Nur auf diesem Rechner erreichbar. Beenden mit Strg+C.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.server_close()
