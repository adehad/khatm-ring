"""Run Python inside a live Blender session through the BlenderMCP add-on socket.

    khatm live path/to/snippet.py
    khatm live -c "print(bpy.data.objects.keys())"

The code can import `khatm`: this package's source folder goes on Blender's
sys.path first. Prints whatever the code printed inside Blender, and exits
non-zero with the Blender-side traceback if the code raised.
"""

import argparse
import json
import socket
import sys
from pathlib import Path

from khatm.paths import SRC

PORT = 9876
PREAMBLE = f"import sys\nif {str(SRC)!r} not in sys.path:\n    sys.path.insert(0, {str(SRC)!r})\n"


def run(code: str, timeout: float = 900.0) -> dict:
    with socket.create_connection(("localhost", PORT), timeout=timeout) as s:
        s.sendall(json.dumps({"type": "execute_code", "params": {"code": PREAMBLE + code}}).encode())
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="khatm live")
    ap.add_argument("file", nargs="?")
    ap.add_argument("-c", "--code")
    a = ap.parse_args(argv)
    if a.code is None and a.file is None:
        ap.error("give a snippet file or -c CODE")
    code = a.code if a.code is not None else Path(a.file).read_text(encoding="utf-8")
    reply = run(code)
    if reply.get("status") != "success":
        print(reply.get("message", reply), file=sys.stderr)
        sys.exit(1)
    print(reply["result"].get("result", ""), end="")


if __name__ == "__main__":
    main()
