"""Replay saved board images through the live backend, as if from a camera.

Each image is sent at --fps for --seconds-per-image, so the gate sees it settle.

Usage:
    .venv/bin/python scripts/replay.py fixtures/whiteboard_1.png --problem two-sum
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from websockets.sync.client import connect


def print_events(ws, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ev = json.loads(ws.recv(timeout=0.5))
        except TimeoutError:
            continue
        except Exception:
            return
        if ev["type"] == "gate":
            continue
        if ev["type"] == "boardState":
            print(f"\n[pass {ev['pass']}]")
            for r in ev["regions"]:
                print(f"  region {r['id']} ({r['type']})")
                for ln in r["lines"]:
                    print(f"    {ln['n']:>2}  {ln['text']}")
            for f in ev["findings"]:
                print(f"  finding {f['id']} t{f['severity']} L{f['line']} [{f['status']}] {f['message']}")
        else:
            print(f"[{ev['type']}] {ev.get('stage', '')} {ev.get('detail', '')}".rstrip())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("images", nargs="+")
    p.add_argument("--problem", default="two-sum")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--fps", type=float, default=2.0)
    p.add_argument("--seconds-per-image", type=float, default=15.0)
    args = p.parse_args()

    sid = httpx.post(f"{args.base}/sessions", json={"problemId": args.problem}).raise_for_status().json()["sessionId"]
    print(f"session {sid}")
    ws_url = args.base.replace("http", "ws", 1) + f"/sessions/{sid}/ws"
    with connect(ws_url, max_size=None) as ws:
        stop = threading.Event()
        reader = threading.Thread(target=print_events, args=(ws, stop), daemon=True)
        reader.start()
        for path in args.images:
            mime = mimetypes.guess_type(path)[0] or "image/png"
            data_url = f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()
            print(f"\n>> sending {path}")
            end = time.time() + args.seconds_per_image
            while time.time() < end:
                ws.send(json.dumps({"type": "frame", "imageData": data_url,
                                    "capturedAt": datetime.now(timezone.utc).isoformat()}))
                time.sleep(1 / args.fps)
        stop.set()
        reader.join(timeout=2)


if __name__ == "__main__":
    main()
