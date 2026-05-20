from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from src.utils.state_serialization import (
    serialize_messages,
    serialize_state_for_event,
    to_json,
)


class StateObject:
    def __init__(self):
        self.status = "running"
        self.messages = [HumanMessage(content="hello")]


def test_serialize_messages_converts_langchain_messages():
    messages = [
        HumanMessage(content="你好", id="user-1"),
        AIMessage(content="ok", id="ai-1"),
    ]

    result = serialize_messages(messages)

    assert result == [
        {
            "type": "human",
            "content": "你好",
            "id": "user-1",
            "name": None,
            "tool_calls": None,
            "additional_kwargs": {},
        },
        {
            "type": "ai",
            "content": "ok",
            "id": "ai-1",
            "name": None,
            "tool_calls": [],
            "additional_kwargs": {},
        },
    ]


def test_serialize_state_for_event_excludes_messages_by_default():
    state = {"status": "done", "messages": [HumanMessage(content="hidden")]}

    result = serialize_state_for_event(state)

    assert result == {"status": "done"}


def test_serialize_state_for_event_can_include_mapping_messages():
    state = {"status": "done", "messages": [HumanMessage(content="visible")]}

    result = serialize_state_for_event(state, include_messages=True)

    assert result["status"] == "done"
    assert result["messages"][0]["type"] == "human"
    assert result["messages"][0]["content"] == "visible"


def test_serialize_state_for_event_can_include_object_messages():
    result = serialize_state_for_event(StateObject(), include_messages=True)

    assert result["status"] == "running"
    assert result["messages"][0]["type"] == "human"
    assert result["messages"][0]["content"] == "hello"


def test_to_json_encodes_paths_and_messages():
    payload = {
        "path": Path("data/output.jpg"),
        "message": HumanMessage(content="caption"),
    }

    result = to_json(payload)

    assert '"path": "data/output.jpg"' in result
    assert '"type": "human"' in result
    assert '"content": "caption"' in result
