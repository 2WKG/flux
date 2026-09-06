"""Capture ONE real `POST /ask` SSE stream from the real app, over real HTTP.

Why this exists.  `web/src/main-assistant/MainAssistant.tsx` reads
`tool_result.result.scene_action`.  A hand-written fixture cannot tell you
whether the server actually sends that field: the previous revision of the seam
read `ToolOutput.status`, its fixtures were copied from the generated type
definition, every test passed, and the field was stripped by
`copilot/narration.py` before it ever reached a browser.  Decisions 20 and 31
therefore require a capture from a running server.

What is real here: `copilot.app.create_app` on its normal startup path, uvicorn
on a real socket, a real HTTP request, the real `ToolDispatcher` built by
`create_app`, the real interactive service reading the checked-in artifact, the
real `CopilotEventStream` SSE encoder.

What is NOT real, and cannot be on this checkout: the model.  There is no
provider credential here, so `build_ask_backend` returns `None` and the route
takes its documented deployment-injected `tool_provider` path.  The provider is
the only stub; it chooses the tool a model would choose and nothing else.  The
frames written out are the bytes the server put on the wire.
"""

from __future__ import annotations

import json
import pathlib
import socket
import sys
import threading
import time
import urllib.request

import uvicorn

from copilot.app import create_app
from copilot.dispatcher import AssistantText, ToolCall

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "web/src/main-assistant/fixtures/ask-scene-action-frames.json"
ATTEMPT = "attempt_0f1e2d3c4b5a6978"


class ScriptedToolProvider:
    """The stub. It picks one frozen tool; it produces no result and no field."""

    name = "capture-harness"
    model = "scripted"

    async def next_action(self, *, question, history, context, tools, results):
        if results:
            return AssistantText(text="The cascade result is above.")
        return ToolCall(
            call_id="cascade-call-1",
            name="cascade",
            arguments={
                "element_ids": ["line:1"],
                "scenario_id": "interactive",
                "hour": 0,
                "seed": 0,
            },
        )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    app = create_app(tool_provider=ScriptedToolProvider())
    # The capture is only meaningful if the route took the path a deployment
    # takes, not a test double wired around it.
    assert app.state.ask_backend is None, (
        "a provider is configured; this capture would not exercise the dispatcher path"
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        print("server did not start", file=sys.stderr)
        return 1

    try:
        body = json.dumps(
            {
                "attempt_id": ATTEMPT,
                "question": "Run a cascade on line:1.",
                "context": {},
                "history": [],
            }
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/ask",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    # The SSE envelope carries `id:` and `event:` on their own lines; the
    # browser's own decoder folds them into the frame, so the capture must too,
    # or the recorded frames would not be what the client actually reduces.
    frames = []
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        frame_id = None
        frame_type = None
        data = None
        for line in block.splitlines():
            if line.startswith("id:"):
                frame_id = line[len("id:") :].strip()
            elif line.startswith("event:"):
                frame_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if not data:
            continue
        payload = json.loads(data)
        if frame_id is not None:
            payload = {"id": frame_id, **payload}
        if frame_type is not None:
            payload = {**payload, "type": frame_type}
        frames.append(payload)

    kinds = [frame.get("type") for frame in frames]
    scene = next(
        (
            f
            for f in frames
            if f.get("type") == "tool_result"
            and isinstance(f.get("result"), dict)
            and "scene_action" in f["result"]
        ),
        None,
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "captured_from": "POST http://127.0.0.1:<port>/ask against copilot.app.create_app on uvicorn",
                "attempt_id": ATTEMPT,
                "frames": frames,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf8",
    )
    print(f"frames={kinds}")
    print(f"scene_action={'PRESENT' if scene else 'ABSENT'}")
    if scene:
        print(json.dumps(scene["result"]["scene_action"], indent=2))
    return 0 if scene else 2


if __name__ == "__main__":
    raise SystemExit(main())
