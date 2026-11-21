"""Run Python inside a live Blender session through the BlenderMCP add-on socket.

    python scripts/blender_live.py path/to/snippet.py
    python scripts/blender_live.py -c "print(bpy.data.objects.keys())"

Prints whatever the code printed inside Blender. Exits non-zero with the
Blender-side traceback if the code raised.
"""

import argparse
import json
import socket
import sys
from pathlib import Path

PORT = 9876


def run(code: str, timeout: float = 900.0) -> dict:
    with socket.create_connection(("localhost", PORT), timeout=timeout) as s:
        s.sendall(json.dumps({"type": "execute_code", "params": {"code": code}}).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    raise ConnectionError("Blender closed the socket without a reply")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("-c", "--code")
    a = ap.parse_args()
    code = a.code if a.code is not None else Path(a.file).read_text(encoding="utf-8")
    reply = run(code)
    if reply.get("status") != "success":
        print(reply.get("message", reply), file=sys.stderr)
        sys.exit(1)
    print(reply["result"].get("result", ""), end="")


if __name__ == "__main__":
    main()
