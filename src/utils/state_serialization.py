import json
from pathlib import Path
from typing import Any, Dict, Iterable

from langchain_core.messages import BaseMessage


def serialize_messages(messages: list[Any] | None) -> list[dict]:
    """Convert LangChain message objects to JSON-friendly dicts.

    This implementation avoids importing version-specific utilities
    and serializes using common BaseMessage attributes.
    """
    if not messages:
        return []
    result: list[dict] = []
    for m in messages:
        if isinstance(m, BaseMessage):
            result.append(
                {
                    "type": getattr(m, "type", "unknown"),
                    "content": getattr(m, "content", None),
                    "id": getattr(m, "id", None),
                    "name": getattr(m, "name", None),
                    "tool_calls": getattr(m, "tool_calls", None),
                    "additional_kwargs": getattr(m, "additional_kwargs", None),
                }
            )
        else:
            result.append({"type": "unknown", "content": str(m)})
    return result


def serialize_state_for_event(
        state: Dict[str, Any] | Any,
        include_messages: bool = False,
        exclude: Iterable[str] = ("messages",),
) -> Dict[str, Any]:
    """Return a JSON-safe snapshot of the state for SSE or logging."""
    # Support both mapping-like and object-like state
    if hasattr(state, "items"):
        base = {k: v for k, v in state.items() if k not in exclude}
        messages = state.get("messages") if hasattr(state, "get") else None
    else:
        base = {k: getattr(state, k) for k in dir(state) if not k.startswith("_")}
        base = {k: v for k, v in base.items() if k not in exclude}
        messages = getattr(state, "messages", None)

    if include_messages and messages:
        base["messages"] = serialize_messages(messages)

    return base


def _default_encoder(obj: Any) -> Any:
    """Default encoder covering LangChain messages and common non-JSON types."""
    if isinstance(obj, BaseMessage):
        return {
            "type": obj.type,
            "content": obj.content,
            "id": getattr(obj, "id", None),
            "name": getattr(obj, "name", None),
            "tool_calls": getattr(obj, "tool_calls", None),
            "additional_kwargs": getattr(obj, "additional_kwargs", None),
        }
    if isinstance(obj, Path):
        return str(obj)
    # Fallback to string to avoid breaking SSE; adjust if stricter behavior needed
    return str(obj)


def to_json(obj: Any) -> str:
    """Dump object to JSON string with safe defaults for messages and paths."""
    return json.dumps(obj, ensure_ascii=False, default=_default_encoder)
