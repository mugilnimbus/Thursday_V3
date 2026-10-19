"""Turn a captured response body into the response it carried, for traces.

A streamed response arrives as hundreds of small events, one per token, and its first event repeats every tool
definition from the request. Kept as text it is unreadable and is cut long before the answer. What a trace needs is
the response itself: the model's reasoning, its answer, its tool calls and the token counts.

- Responses API stream: the last event (`response.completed`, `.incomplete` or `.failed`) carries the whole response.
- Chat completions stream (the built-in llama.cpp): there is no such event, so the message is put together from
  the chunks, in the shape of a non-streamed chat completion.
- A stream that ended early: what arrived is put together and marked incomplete.
- Anything else is returned as parsed JSON, or as the text it was.
"""

import json
from typing import Any

FINAL_EVENTS = ("response.completed", "response.incomplete", "response.failed")
ECHOED_FROM_REQUEST = ("tools", "instructions", "input")  # already in the request body; repeating them hides the rest


def _events(text: str) -> list[dict[str, Any]]:
    """The JSON objects of a server-sent-event stream; lines that are not JSON (`[DONE]`, a cut line) are skipped."""
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            value = json.loads(line[5:].strip())
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def _from_responses(events: list[dict[str, Any]]) -> dict[str, Any]:
    final = next(
        (e for e in reversed(events) if e.get("type") in FINAL_EVENTS and isinstance(e.get("response"), dict)), None
    )
    if final is not None:
        return {k: v for k, v in final["response"].items() if k not in ECHOED_FROM_REQUEST}
    # The stream ended early: rebuild the items from their pieces.
    items: dict[int, dict[str, Any]] = {}
    model = None
    for event in events:
        kind = event.get("type", "")
        if isinstance(event.get("response"), dict):
            model = event["response"].get("model", model)
        index = event.get("output_index")
        if not isinstance(index, int):
            continue
        if kind in ("response.output_item.added", "response.output_item.done") and isinstance(event.get("item"), dict):
            kept = items.get(index, {})
            items[index] = {**event["item"], **({"_text": kept["_text"]} if "_text" in kept else {})}
            continue
        item = items.setdefault(index, {"type": "message"})
        if kind.endswith(".delta") and isinstance(event.get("delta"), str):
            item["_text"] = item.get("_text", "") + event["delta"]
    output = []
    for _, item in sorted(items.items()):
        text = item.pop("_text", "")
        if item.get("type") == "function_call":
            item["arguments"] = item.get("arguments") or text
        elif text and not item.get("content"):
            item["content"] = [
                {"type": "reasoning_text" if item.get("type") == "reasoning" else "output_text", "text": text}
            ]
        output.append(item)
    return {"status": "incomplete", "model": model, "output": output, "usage": None}


def _from_chat_chunks(events: list[dict[str, Any]]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    calls: dict[int, dict[str, Any]] = {}
    finish, usage, model = None, None, None
    for event in events:
        model = event.get("model", model)
        usage = event.get("usage") or usage
        for choice in event.get("choices") or []:
            finish = choice.get("finish_reason") or finish
            delta = choice.get("delta") or {}
            message["content"] += delta.get("content") or ""
            if delta.get("reasoning_content"):
                message["reasoning_content"] = message.get("reasoning_content", "") + delta["reasoning_content"]
            for piece in delta.get("tool_calls") or []:
                call = calls.setdefault(
                    piece.get("index", 0), {"type": "function", "function": {"name": "", "arguments": ""}}
                )
                call["id"] = piece.get("id") or call.get("id")
                function = piece.get("function") or {}
                call["function"]["name"] += function.get("name") or ""
                call["function"]["arguments"] += function.get("arguments") or ""
    if calls:
        message["tool_calls"] = [call for _, call in sorted(calls.items())]
    return {"model": model, "choices": [{"message": message, "finish_reason": finish}], "usage": usage}


def read_response(text: str | None) -> Any:
    if not text:
        return None
    if "data:" in text:
        events = _events(text)
        if any(str(e.get("type", "")).startswith("response.") for e in events):
            return _from_responses(events)
        if any("choices" in e for e in events):
            return _from_chat_chunks(events)
    try:
        return json.loads(text)
    except ValueError:
        return text
