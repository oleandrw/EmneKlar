"""Serve the fake Canvas over HTTP (Playwright tests and local UI development only).

    python -m tests.fakes.serve_fake_canvas --port 8790
"""

from __future__ import annotations

import argparse

import uvicorn

from tests.fakes.fake_canvas import create_fake_canvas, seed_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    origin = f"http://127.0.0.1:{args.port}"
    uvicorn.run(create_fake_canvas(seed_state(origin)), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
