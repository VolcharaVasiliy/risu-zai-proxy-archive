import json
import threading
import time
import uuid

try:
    from py.provider_registry import complete_non_stream
    from py.zai_proxy import debug_log
except ImportError:
    from provider_registry import complete_non_stream
    from zai_proxy import debug_log


_STATE_LOCK = threading.RLock()
_STATE_TTL_SECONDS = 6 * 60 * 60
_RESPONSE_STATE = {}


def _now() -> int:
    return int(time.time())


def _event(event_type: str, **fields) -> dict:
    return {"event_id": f"evt_{uuid.uuid4().hex}", "type": event_type, **fields}


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"input_text", "output_text", "text"}:
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _content_to_chat_content(content):
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type in {"input_text", "output_text", "text"}:
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append({"type": "text", "text": text})
                continue

            if item_type == "input_image":
                image_url = str(item.get("image_url") or "").strip()
                file_url = str(item.get("file_url") or "").strip()
                file_id = str(item.get("file_id") or "").strip()
                url = image_url or file_url
                if url:
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                elif file_id:
                    parts.append({"type": "text", "text": f"[image file_id: {file_id}]"})
                continue

            if item_type == "input_file":
                filename = str(item.get("filename") or "file").strip()
                file_url = str(item.get("file_url") or "").strip()
                file_id = str(item.get("file_id") or "").strip()
                file_data = str(item.get("file_data") or "").strip()
                text = f"[file: {filename}]"
                if file_url:
                    text = f"{text} {file_url}"
                elif file_id:
                    text = f"{text} {file_id}"
                elif file_data:
                    text = f"{text} {file_data[:80]}"
                parts.append({"type": "text", "text": text})
                continue

        if not parts:
            return ""
        if len(parts) == 1 and parts[0].get("type") == "text":
            return parts[0]["text"]
        return parts

    if content is None:
        return ""
    return str(content)


def _normalize_message_item(item: dict):
    item_type = str(item.get("type") or "message").strip()

    if item_type == "message":
        role = str(item.get("role") or "user").strip() or "user"
        content = _content_to_chat_content(item.get("content"))
        message = {"role": role, "content": content}
        if item.get("name"):
            message["name"] = str(item["name"])
        if item.get("tool_call_id"):
            message["tool_call_id"] = str(item["tool_call_id"])
        if item.get("tool_calls"):
            message["tool_calls"] = item["tool_calls"]
        return message

    if item_type == "input_text":
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        return {"role": "user", "content": text}

    if item_type == "input_image":
        content = _content_to_chat_content([item])
        if not content:
            return None
        return {"role": "user", "content": content}

    if item_type == "input_file":
        content = _content_to_chat_content([item])
        if not content:
            return None
        return {"role": "user", "content": content}

    if item_type == "function_call_output":
        call_id = str(item.get("call_id") or item.get("tool_call_id") or item.get("id") or "").strip()
        output = item.get("output")
        content = output if isinstance(output, str) else _content_to_chat_content(output)
        if not content and output is not None:
            content = _content_text(output)
        message = {
            "role": "tool",
            "content": content or "",
        }
        if call_id:
            message["tool_call_id"] = call_id
        if item.get("name"):
            message["name"] = str(item["name"])
        return message

    if item_type == "function_call":
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        call_id = str(item.get("call_id") or item.get("id") or "").strip() or f"call_{uuid.uuid4().hex}"
        name = str(item.get("name") or function.get("name") or "").strip()
        arguments = item.get("arguments")
        if arguments is None and function:
            arguments = function.get("arguments")
        if isinstance(arguments, (dict, list)):
            arguments = json.dumps(arguments, ensure_ascii=False)
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": str(arguments or ""),
                    },
                }
            ],
        }

    return None


def _input_to_messages(payload: dict) -> list:
    messages = []

    instructions = payload.get("instructions")
    instructions_text = _content_text(instructions).strip()
    if instructions_text:
        messages.append({"role": "system", "content": instructions_text})

    raw_input = payload.get("input")
    if raw_input is None and isinstance(payload.get("messages"), list):
        raw_input = payload.get("messages")

    if isinstance(raw_input, str):
        text = raw_input.strip()
        if text:
            messages.append({"role": "user", "content": text})
        return messages

    if isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_message_item(item)
            if normalized:
                messages.append(normalized)
        return messages

    if isinstance(payload.get("messages"), list):
        for item in payload.get("messages"):
            if not isinstance(item, dict):
                continue
            normalized = _normalize_message_item({**item, "type": "message"})
            if normalized:
                messages.append(normalized)

    return messages


def _merge_messages(existing: list, incoming: list) -> list:
    if not existing:
        return list(incoming)
    if not incoming:
        return list(existing)
    if len(incoming) >= len(existing) and incoming[: len(existing)] == existing:
        return list(incoming)
    if len(incoming) == 1:
        return list(existing) + list(incoming)
    return list(incoming)


def _session_key(payload: dict) -> str:
    conversation = payload.get("conversation")
    conversation_id = ""
    if isinstance(conversation, dict):
        conversation_id = str(conversation.get("id") or "").strip()
    return str(
        payload.get("previous_response_id")
        or payload.get("conversation_id")
        or conversation_id
        or payload.get("response_id")
        or ""
    ).strip()


def _prune_state():
    cutoff = time.time() - _STATE_TTL_SECONDS
    with _STATE_LOCK:
        stale_keys = [key for key, state in _RESPONSE_STATE.items() if float(state.get("updated_at") or 0) < cutoff]
        for key in stale_keys:
            _RESPONSE_STATE.pop(key, None)


def _load_state(payload: dict):
    key = _session_key(payload)
    if not key:
        return "", {}

    _prune_state()
    with _STATE_LOCK:
        return key, dict(_RESPONSE_STATE.get(key) or {})


def _save_state(response_id: str, state: dict):
    if not response_id:
        return

    state = dict(state)
    state["updated_at"] = time.time()
    with _STATE_LOCK:
        _RESPONSE_STATE[response_id] = state


def _chat_payload_from_request(payload: dict, provider_id: str) -> tuple[list, dict]:
    state_key, state = _load_state(payload)
    stored_messages = list(state.get("messages") or [])
    incoming_messages = _input_to_messages(payload)
    messages = _merge_messages(stored_messages, incoming_messages)

    if provider_id == "zai":
        # Z.ai drops system/tool messages in its own adapter, so keep the request shape
        # conservative and let the provider decide what it can honor.
        pass

    chat_payload = dict(payload)
    chat_payload.pop("input", None)
    chat_payload["messages"] = messages
    chat_payload["stream"] = False

    for field in (
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "reasoning_effort",
        "seed",
        "stop",
        "metadata",
        "user",
    ):
        if field in payload:
            chat_payload[field] = payload[field]

    return messages, {"state_key": state_key, "stored_state": state, "chat_payload": chat_payload}


def _assistant_message_from_result(result: dict) -> dict:
    choices = result.get("choices") or [{}]
    message = ((choices[0] or {}).get("message") or {})
    content = _content_text(message.get("content")).strip()
    reasoning = _content_text(message.get("reasoning_content")).strip()
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []

    assistant_message = {"role": "assistant", "content": content}
    if reasoning:
        assistant_message["reasoning_content"] = reasoning
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    return assistant_message


def _tool_calls_from_result(result: dict) -> list:
    choices = result.get("choices") or [{}]
    message = ((choices[0] or {}).get("message") or {})
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        return tool_calls
    return []


def _output_items_from_result(result: dict) -> list:
    choices = result.get("choices") or [{}]
    message = ((choices[0] or {}).get("message") or {})
    content = _content_text(message.get("content")).strip()
    tool_calls = _tool_calls_from_result(result)

    output = []
    for tool_call in tool_calls:
        function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
        call_id = str(tool_call.get("id") or tool_call.get("call_id") or "").strip() or f"call_{uuid.uuid4().hex}"
        item_id = f"fc_{uuid.uuid4().hex}"
        arguments = function.get("arguments") if function else tool_call.get("arguments")
        if isinstance(arguments, (dict, list)):
            arguments = json.dumps(arguments, ensure_ascii=False)
        output.append(
            {
                "id": item_id,
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": str(function.get("name") or tool_call.get("name") or ""),
                "arguments": str(arguments or ""),
            }
        )

    if content:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        )

    if not output:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": ""}],
            }
        )

    return output


def _response_object_from_result(result: dict, response_id: str, previous_response_id: str, payload: dict) -> dict:
    created_at = _now()
    choices = result.get("choices") or [{}]
    message = ((choices[0] or {}).get("message") or {})
    content = _content_text(message.get("content")).strip()
    tool_calls = _tool_calls_from_result(result)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}

    response = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "model": result.get("model") or payload.get("model") or "",
        "output": _output_items_from_result(result),
        "output_text": content,
        "previous_response_id": previous_response_id or None,
        "parallel_tool_calls": bool(payload.get("parallel_tool_calls", True)),
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }

    instructions = payload.get("instructions")
    if instructions is not None:
        response["instructions"] = instructions

    metadata = payload.get("metadata")
    if metadata is not None:
        response["metadata"] = metadata

    if tool_calls:
        response["tool_calls"] = [
            {
                "id": item["call_id"],
                "type": "function",
                "status": "completed",
                "name": item["name"],
                "arguments": item["arguments"],
            }
            for item in response["output"]
            if item.get("type") == "function_call"
        ]

    return response


def _stream_events_from_response(response: dict):
    response_id = response["id"]
    output = response.get("output") or []
    completed = dict(response)
    completed["status"] = "completed"
    created = {"type": "response.created", "response": {**response, "status": "in_progress"}}
    yield _event(created["type"], response=created["response"])

    for index, item in enumerate(output):
        yield _event("response.output_item.added", response_id=response_id, output_index=index, item=item)

        if item.get("type") == "message":
            text = _content_text(item.get("content")).strip()
            if text:
                yield _event(
                    "response.output_text.delta",
                    response_id=response_id,
                    item_id=item["id"],
                    output_index=index,
                    content_index=0,
                    delta=text,
                )
                yield _event(
                    "response.output_text.done",
                    response_id=response_id,
                    item_id=item["id"],
                    output_index=index,
                    content_index=0,
                    text=text,
                )
            yield _event("response.output_item.done", response_id=response_id, output_index=index, item=item)
            continue

        if item.get("type") == "function_call":
            yield _event(
                "response.function_call_arguments.done",
                response_id=response_id,
                item_id=item["id"],
                output_index=index,
                call_id=item["call_id"],
                arguments=item["arguments"],
            )
            yield _event("response.output_item.done", response_id=response_id, output_index=index, item=item)

    yield _event("response.completed", response=completed)
    yield _event("response.done", response=completed)


def complete_response(provider_id: str, credentials: dict, payload: dict):
    previous_response_id = _session_key(payload)
    messages, context = _chat_payload_from_request(payload, provider_id)
    chat_payload = context["chat_payload"]
    result, meta = complete_non_stream(provider_id, credentials, chat_payload)

    response_id = f"resp_{uuid.uuid4().hex}"
    response = _response_object_from_result(result, response_id, previous_response_id, payload)
    assistant_message = _assistant_message_from_result(result)

    if payload.get("store", True) is not False:
        next_messages = list(messages)
        if assistant_message:
            next_messages.append(assistant_message)
        _save_state(
            response_id,
            {
                "messages": next_messages,
                "provider": provider_id,
                "model": response.get("model") or payload.get("model") or "",
                "previous_response_id": previous_response_id,
            },
        )

    meta = dict(meta or {})
    meta.update(
        {
            "provider": provider_id,
            "response_id": response_id,
            "previous_response_id": previous_response_id,
            "message_count": len(messages),
            "output_text_length": len(response.get("output_text") or ""),
            "tool_call_count": len(_tool_calls_from_result(result)),
        }
    )

    debug_log("responses_complete", **meta)
    return response, meta


def stream_response_events(provider_id: str, credentials: dict, payload: dict):
    response, meta = complete_response(provider_id, credentials, payload)
    debug_log("responses_stream", provider=provider_id, response_id=response["id"], tool_call_count=meta.get("tool_call_count", 0))
    for event in _stream_events_from_response(response):
        yield event
