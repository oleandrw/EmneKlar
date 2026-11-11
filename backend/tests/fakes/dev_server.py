"""Developer preview: EmneKlar + fake Canvas, throw-away data, in-memory secrets.

    python backend/tests/fakes/dev_server.py [--port 8766] [--canvas-port 8790] [--configured] [--demo]
                                             [--data-dir DIR]

Open http://127.0.0.1:<port>/auth/launch?token=dev-preview-token. With
``--configured`` the Canvas connection is pre-filled so the setup wizard is
skipped (used by the Playwright tests). ``--demo`` adds representative test data
for trying the whole fix-and-publish workflow locally: a Blueprint course with an
associated course whose content is locked, a page with many images and dead
links, and a fake AI provider for KI-forslag til alt-tekst (nothing leaves the
machine). «Publiser til Canvas» writes to the fake Canvas only. Never used by end users.
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
from emneklar.core.auth.secrets import CANVAS_TOKEN, MemorySecretStore, ai_key_name  # noqa: E402
from emneklar.core.container import AppContainer  # noqa: E402
from emneklar.core.storage.settings import CanvasIdentity  # noqa: E402
from emneklar.main import create_app  # noqa: E402
from tests.fakes.fake_ai import fake_ai_transport  # noqa: E402
from tests.fakes.fake_canvas import (  # noqa: E402
    TOKEN,
    add_blueprint_child,
    add_demo_data,
    create_fake_canvas,
    fake_youtube_lookup,
    seed_state,
)

DEV_TOKEN = "dev-preview-token"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--canvas-port", type=int, default=8790)
    parser.add_argument("--configured", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Blueprint-emner, mange funn og falsk KI for alt-tekst")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    canvas_origin = f"http://127.0.0.1:{args.canvas_port}"
    state = seed_state(canvas_origin)
    if args.demo:
        add_blueprint_child(state)
        add_demo_data(state)
    fake = uvicorn.Server(uvicorn.Config(create_fake_canvas(state), host="127.0.0.1",
                                         port=args.canvas_port, log_level="warning"))
    threading.Thread(target=fake.run, daemon=True).start()
    time.sleep(0.5)

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="emneklar-dev-"))
    config = RuntimeConfig(port=args.port, data_dir=data_dir, dev_mode=True, dev_launch_token=DEV_TOKEN,
                           secret_backend="memory", parser_isolation=False, allow_insecure_canvas=True,
                           dev_origins=("http://127.0.0.1:5173",))
    container = AppContainer(config, secret_store=MemorySecretStore(),
                             ai_transport=fake_ai_transport() if args.demo else None,
                             youtube_lookup=fake_youtube_lookup)  # never contacts YouTube
    if args.configured or args.demo:
        container.migrate()
        container.secrets.set(CANVAS_TOKEN, TOKEN)

        def configure(s):  # type: ignore[no-untyped-def]
            s.setup_completed = True
            s.canvas.base_url = canvas_origin
            s.canvas.identity = CanvasIdentity(id="42", name="Kari Lærer")
            s.current_course_id = "101"
            if args.demo:
                s.privacy.allow_external_ai = True  # the «external» provider is the local fake above
                for provider in s.ai.providers:
                    provider.enabled = provider.id == "anthropic"

        container.settings.update(configure)
        if args.demo:
            container.secrets.set(ai_key_name("anthropic"), "sk-ant-fake-dev-preview-0000000000")
    print(f"EmneKlar (dev): http://127.0.0.1:{args.port}/auth/launch?token={DEV_TOKEN}", flush=True)
    print(f"Fake Canvas: {canvas_origin}  token: {TOKEN}", flush=True)
    print(f"Data folder (throw-away): {data_dir}", flush=True)
    if args.demo:
        # ASCII only: the Windows console (cp1252) cannot print arrows or Norwegian quotes without PYTHONUTF8.
        print("Demo: Blueprint course 102 -> associated course 104 (locked page), 'Bildegalleri' in course 101, "
              "fake AI provider for alt text.", flush=True)
    uvicorn.run(create_app(container), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
