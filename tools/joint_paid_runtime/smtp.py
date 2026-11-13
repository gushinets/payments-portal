"""Loopback-only disposable SMTP sink for real email verification, never relay."""

import hashlib
import json
import os
from email import policy
from email.parser import BytesParser
from pathlib import Path
from socketserver import StreamRequestHandler, ThreadingTCPServer


class MailSink(StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(10)
        self.wfile.write(b"220 localhost synthetic SMTP\r\n")
        while line := self.rfile.readline(65536):
            command = line.split(b" ", 1)[0].strip().upper()
            if command == b"DATA":
                self.wfile.write(b"354 End with a dot\r\n")
                parts = []
                while (part := self.rfile.readline(65536)) not in (b".\r\n", b""):
                    parts.append(part[1:] if part.startswith(b"..") else part)
                message = BytesParser(policy=policy.default).parsebytes(b"".join(parts))
                recipient = str(message["To"])
                key = hashlib.sha256(recipient.encode()).hexdigest()
                path = Path(os.environ["ANY766_RUN_DIR"]) / f"mail-{key}.json"
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps({"recipient": recipient, "body": message.get_content()})
                )
                temporary.chmod(0o600)
                temporary.replace(path)
                self.wfile.write(b"250 Stored locally\r\n")
            elif command == b"QUIT":
                self.wfile.write(b"221 Bye\r\n")
                return
            elif command in {b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET", b"NOOP"}:
                self.wfile.write(b"250 localhost\r\n")
            else:
                self.wfile.write(b"502 Unsupported\r\n")


if __name__ == "__main__":
    with ThreadingTCPServer(
        ("127.0.0.1", int(os.environ["SMTP_PORT"])), MailSink
    ) as server:
        server.daemon_threads = True
        (Path(os.environ["ANY766_RUN_DIR"]) / "smtp.ready").touch()
        server.serve_forever()
