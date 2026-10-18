"""Synthetic user: ask one question through the real Streamlit WebSocket, like a browser does.

    python scripts/ui-probe.py http://127.0.0.1:8501 "Why was the v2.1 release delayed?"

Run it with the app's own image (it needs streamlit's protobuf classes and websockets):

    kubectl -n reasoning-engine port-forward svc/reasoning-engine 18080:80 &
    docker run --rm --network host -v "$PWD/scripts:/probe:ro" --entrypoint python \
      reasoning-engine:<tag> /probe/ui-probe.py http://127.0.0.1:18080 "Why was the v2.1 release delayed?"

Exit 0 when the page renders an answer header for the question; prints the answer's first line.
This exercises Service -> pod -> Streamlit session -> pipeline.ask in the server process, so the
`ask.completed` event appears in `kubectl logs`.
"""
from __future__ import annotations

import asyncio
import sys

import websockets
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg


def _elements(msgs):
    for m in msgs:
        if m.WhichOneof("type") == "delta" and m.delta.WhichOneof("type") == "new_element":
            yield m.delta.new_element


async def _run(ws, widget_states=None):
    back = BackMsg()
    back.rerun_script.query_string = ""
    if widget_states:
        back.rerun_script.widget_states.widgets.extend(widget_states)
    await ws.send(back.SerializeToString())
    msgs = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=60)
        msg = ForwardMsg()
        msg.ParseFromString(raw)
        msgs.append(msg)
        if msg.WhichOneof("type") == "script_finished":
            return msgs


async def main(base: str, question: str) -> int:
    url = base.replace("http", "ws", 1).rstrip("/") + "/_stcore/stream"
    async with websockets.connect(url, origin=base.rstrip("/"), max_size=None) as ws:
        first = await _run(ws)
        text_input = button = None
        for el in _elements(first):
            kind = el.WhichOneof("type")
            if kind == "text_input" and text_input is None:
                text_input = el.text_input.id
            if kind == "button" and el.button.is_form_submitter and button is None:
                button = el.button.id
        if not (text_input and button):
            print("FAIL: ask form not found on the page")
            return 1

        from streamlit.proto.WidgetStates_pb2 import WidgetState
        q = WidgetState(id=text_input, string_value=question)
        b = WidgetState(id=button, trigger_value=True)
        second = await _run(ws, [q, b])

        texts = []
        for el in _elements(second):
            if el.WhichOneof("type") == "markdown":
                texts.append(el.markdown.body)
        header = next((t for t in texts if t.startswith("### Answer")), None)
        if header is None:
            print("FAIL: no answer rendered")
            return 1
        body = next((t for t in texts[texts.index(header) + 1:]
                     if t.strip() and not t.startswith("Question:")), "")
        print("PASS:", header)
        print("first line:", body.splitlines()[0][:160] if body else "")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
