"""Stdlib HTTP client tests against a local server."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ffdetails.errors import FetchError
from ffdetails.http import UrllibClient


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/ok":
            body = json.dumps({"pts_ppr": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/text":
            body = b"<tbody></tbody>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def test_get_json_and_text(self) -> None:
        client = UrllibClient(timeout=5)
        self.assertEqual(client.get_json(self.base + "/ok"), {"pts_ppr": 1})
        self.assertIn("tbody", client.get_text(self.base + "/text"))

    def test_http_error_becomes_fetch_error(self) -> None:
        client = UrllibClient(timeout=5)
        with self.assertRaises(FetchError):
            client.get_json(self.base + "/missing")


if __name__ == "__main__":
    unittest.main()
