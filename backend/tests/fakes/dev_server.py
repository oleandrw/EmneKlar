"""Developer preview: EmneKlar + fake Canvas, throw-away data, in-memory secrets.

    python backend/tests/fakes/dev_server.py [--port 8766] [--canvas-port 8790] [--configured]

Open http://127.0.0.1:<port>/auth/launch?token=dev-preview-token. With
``--configured`` the Canvas connection is pre-filled so the setup wizard is
skipped (used by the Playwright tests). Never used by end users.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402

from emneklar.config import RuntimeConfig  # noqa: E402
from emneklar.core.auth.secrets import CANVAS_TOKEN, MemorySecretStore  # noqa: E402
from emneklar.core.container import AppContainer  # noqa: E402
from emneklar.core.storage.settings import CanvasIdentity  # noqa: E402
from emneklar.main import create_app  # noqa: E402
from tests.fakes.fake_canvas import TOKEN, create_fake_canvas, seed_state  # noqa: E402

DEV_TOKEN = "dev-preview-token"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--canvas-port", type=int, default=8790)
    parser.add_argument("--configured", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    canvas_origin = f"http://127.0.0.1:{args.canvas_port}"
    fake = uvicorn.Server(uvicorn.Config(create_fake_canvas(seed_state(canvas_origin)), host="127.0.0.1",
                                         port=args.canvas_port, log_level="warning"))
    threading.Thread(target=fake.run, daemon=True).start()
    time.sleep(0.5)

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="emneklar-dev-"))
    config = RuntimeConfig(port=args.port, data_dir=data_dir, dev_mode=True, dev_launch_token=DEV_TOKEN,
                           secret_backend="memory", parser_isolation=False, allow_insecure_canvas=True,
                           dev_origins=("http://127.0.0.1:5173",))
    container = AppContainer(config, secret_store=MemorySecretStore())
    if args.configured:
        container.migrate()
        container.secrets.set(CANVAS_TOKEN, TOKEN)

        def configure(s):  # type: ignore[no-untyped-def]
            s.setup_completed = True
            s.canvas.base_url = canvas_origin
            s.canvas.identity = CanvasIdentity(id="42", name="Kari Lærer")
            s.current_course_id = "101"

        container.settings.update(configure)
    print(f"EmneKlar (dev): http://127.0.0.1:{args.port}/auth/launch?token={DEV_TOKEN}", flush=True)
    print(f"Fake Canvas: {canvas_origin}  token: {TOKEN}", flush=True)
    uvicorn.run(create_app(container), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
