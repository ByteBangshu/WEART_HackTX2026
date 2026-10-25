import argparse
import contextlib
import io
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import computer_receiver
import pi_pipeline


class FakeMuse:
    def badge(self, image):
        assert Path(image).exists()
        return {"name": "Avery Chen", "company": "Example Robotics", "job_title": "Engineer"}

    def research(self, badge):
        return {"source_url": "https://example.com/team/avery", "facts": ["Builds embedded controls"]}

    def advise(self, badge, context, resume):
        assert "MIPS" in resume
        return {"summary": "Avery builds embedded controls.", "resume_overlap": "Your MIPS emulator relates to embedded systems.",
                "talking_points": ["Ask about device testing.", "Mention your emulator."],
                "opening_question": "How do you test embedded controls?"}


class PipelineTest(unittest.TestCase):
    def test_api_key_uses_bearer_auth(self):
        client = pi_pipeline.MuseSpark("test-api-key")
        self.assertEqual(client.headers["Authorization"], "Bearer test-api-key")

    def test_esp32_snapshot_to_terminal(self):
        class CameraHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/capture":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(b"\xff\xd8sample-jpeg\xff\xd9")

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            resume = Path(directory) / "resume.txt"
            resume.write_text("MIPS emulator in C", encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), CameraHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            args = argparse.Namespace(image=None, esp32_url=f"http://127.0.0.1:{server.server_port}/capture",
                                      resume=str(resume), receiver=None, token="")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = pi_pipeline.run(args, FakeMuse())
                self.assertIn("How do you test embedded controls?", result)
            finally:
                server.shutdown()
                server.server_close()

    def test_end_to_end_terminal_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "badge.jpg"
            resume = Path(directory) / "resume.txt"
            image.write_bytes(b"fake badge (model simulated)")
            resume.write_text("MIPS emulator in C", encoding="utf-8")
            server = ThreadingHTTPServer(("127.0.0.1", 0), computer_receiver.Handler)
            server.token = "test-token"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            args = argparse.Namespace(image=str(image), resume=str(resume),
                                      receiver=f"http://127.0.0.1:{server.server_port}", token="test-token")
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    result = pi_pipeline.run(args, FakeMuse())
                self.assertIn("How do you test embedded controls?", result)
                self.assertIn("Avery Chen", out.getvalue())
                self.assertIn("SOURCE: https://example.com/team/avery", out.getvalue())
            finally:
                server.shutdown()
                server.server_close()

    def test_reject_missing_badge_name(self):
        class MissingName(FakeMuse):
            def badge(self, image):
                return {"name": "", "company": "Example Robotics"}
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "badge.jpg"
            resume = Path(directory) / "resume.txt"
            image.write_bytes(b"fake")
            resume.write_text("MIPS emulator", encoding="utf-8")
            args = argparse.Namespace(image=str(image), resume=str(resume), receiver=None, token="")
            with self.assertRaisesRegex(ValueError, "name and company"):
                pi_pipeline.run(args, MissingName())


if __name__ == "__main__":
    unittest.main()
