"""Run this on your computer to display results sent by the Pi."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/result" or self.headers.get("X-Shared-Token") != self.server.token:
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 20000:
                self.send_error(413)
                return
            message = json.loads(self.rfile.read(length))
            if not isinstance(message.get("text"), str):
                self.send_error(400)
                return
        except (ValueError, KeyError, json.JSONDecodeError):
            self.send_error(400)
            return
        print("\n" + "=" * 60 + "\n" + message["text"] + "\n" + "=" * 60, flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


def main():
    parser = argparse.ArgumentParser(description="Display Pi networking results on this computer")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    token = os.getenv("RECEIVER_TOKEN")
    if not token:
        parser.error("Set RECEIVER_TOKEN to the same secret on both machines")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.token = token
    print(f"Listening on port {args.port}; press Ctrl+C to stop", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
