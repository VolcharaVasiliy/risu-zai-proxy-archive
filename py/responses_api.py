import json
import re
import threading
import time
import uuid

try:
    from py.agent_tools import tool_request_supported, unsupported_tool_message
    from py.openai_stream import OpenAIStreamBuilder, openai_chunk
    from py.provider_registry import complete_non_stream
    from py.zai_proxy import debug_log
except ImportError:
    from agent_tools import tool_request_supported, unsupported_tool_message
    from openai_stream import OpenAIStreamBuilder, openai_chunk
    from provider_registry import complete_non_stream
    from zai_proxy import debug_log


_STATE_LOCK = threading.RLock()
_STATE_TTL_SECONDS = 6 * 60 * 60
_RESPONSE_STATE = {}
_TOOL_CALL_RE = re.compile(
    r"^\s*tool_call\s*:\s*(?P<name>[A-Za-z0-9_.:-]+)(?:\s+for\s+(?P<args>.*))?\s*$",
    re.IGNORECASE,
)
_TOOL_WAIT_RE = re.compile(
    r"^\s*\(?\s*wait(?:ing)?\s+for\s+tool\s+output.*\)?\s*$", re.IGNORECASE
)
_SHELL_TOOL_NAMES = {"bash", "shell", "powershell", "pwsh", "cmd", "terminal"}
_PATH_TOOL_NAMES = {"ls", "list", "read_file", "read", "cat", "open", "image"}
_STATEFUL_REQUEST_FIELDS = (
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
)


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
            if isinstance(item, dict) and item.get("type") in {
                "input_text",
                "output_text",
                "text",
            }:
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _single_function_tool(request_config: dict):
    tools = request_config.get("tools")
    if not isinstance(tools, list) or len(tools) != 1:
        return None
    tool = tools[0] if isinstance(tools[0], dict) else None
    if not tool:
        return None
    if str(tool.get("type") or "").strip() != "function":
        return None
    function = tool.get("function") if isinstance(tool.get("function"), dict) else None
    name = str((function or {}).get("name") or "").strip()
    if not name:
        return None
    return tool


def _pseudo_tool_call_arguments(name: str, args_text: str) -> str:
    tool_name = str(name or "").strip().lower()
    text = str(args_text or "").strip()

    if tool_name in _SHELL_TOOL_NAMES:
        return json.dumps({"command": text}, ensure_ascii=False)

    if tool_name in _PATH_TOOL_NAMES:
        lowered = text.lower()
        if lowered.startswith("absolute_path "):
            return json.dumps({"absolute_path": text[14:].strip()}, ensure_ascii=False)
        if lowered.startswith("relative_path "):
            return json.dumps({"relative_path": text[14:].strip()}, ensure_ascii=False)
        if lowered.startswith("path "):
            return json.dumps({"path": text[5:].strip()}, ensure_ascii=False)
        if lowered.startswith("file "):
            return json.dumps({"file": text[5:].strip()}, ensure_ascii=False)
        if not text:
            return json.dumps({}, ensure_ascii=False)
        return json.dumps({"path": text}, ensure_ascii=False)

    if not text:
        return json.dumps({}, ensure_ascii=False)
    return json.dumps({"input": text}, ensure_ascii=False)


def _extract_pseudo_tool_calls(content) -> tuple[str, list]:
    raw_text = _content_text(content)
    if not raw_text:
        return "", []

    plain_lines = []
    calls = []

    for line in raw_text.splitlines():
        tool_match = _TOOL_CALL_RE.match(line)
        if tool_match:
            name = str(tool_match.group("name") or "").strip()
            args_text = str(tool_match.group("args") or "").strip()
            call_id = f"call_{uuid.uuid4().hex}"
            calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": _pseudo_tool_call_arguments(name, args_text),
                    },
                }
            )
            continue

        if _TOOL_WAIT_RE.match(line):
            continue

        plain_lines.append(line)

    return "\n".join(plain_lines).strip(), calls


def _normalize_result_tool_calls(result: dict, request_config: dict) -> dict:
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    existing_calls = message.get("tool_calls")
    if isinstance(existing_calls, list) and existing_calls:
        return result

    content = _content_text(message.get("content")).strip()
    if not content or not (content.startswith("{") or content.startswith("[")):
        return result

    tool = _single_function_tool(request_config)
    if not tool:
        return result

    try:
        parsed = json.loads(content)
    except Exception:
        return result

    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    normalized_message = dict(message)
    normalized_message["content"] = ""
    normalized_message["tool_calls"] = [
        {
            "id": f"call_{uuid.uuid4().hex}",
            "type": "function",
            "function": {
                "name": str(function.get("name") or ""),
                "arguments": json.dumps(parsed, ensure_ascii=False),
            },
        }
    ]

    normalized_choice = dict(choices[0] or {})
    normalized_choice["message"] = normalized_message
    normalized_choice["finish_reason"] = "tool_calls"

    normalized_result = dict(result)
    normalized_result["choices"] = [normalized_choice] + list(choices[1:])
    return normalized_result


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
                    parts.append(
                        {"type": "text", "text": f"[image file_id: {file_id}]"}
                    )
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
        call_id = str(
            item.get("call_id") or item.get("tool_call_id") or item.get("id") or ""
        ).strip()
        output = item.get("output")
        content = (
            output if isinstance(output, str) else _content_to_chat_content(output)
        )
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
        function = (
            item.get("function") if isinstance(item.get("function"), dict) else {}
        )
        call_id = (
            str(item.get("call_id") or item.get("id") or "").strip()
            or f"call_{uuid.uuid4().hex}"
        )
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
        stale_keys = [
            key
            for key, state in _RESPONSE_STATE.items()
            if float(state.get("updated_at") or 0) < cutoff
        ]
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


def get_stored_response(response_id: str) -> dict | None:
    response_id = str(response_id or "").strip()
    if not response_id:
        return None
    _prune_state()
    with _STATE_LOCK:
        state = _RESPONSE_STATE.get(response_id) or {}
        response = state.get("response")
        return dict(response) if isinstance(response, dict) else None


def delete_stored_response(response_id: str) -> bool:
    response_id = str(response_id or "").strip()
    if not response_id:
        return False
    with _STATE_LOCK:
        return _RESPONSE_STATE.pop(response_id, None) is not None


def _request_config_from_payload(payload: dict, state: dict | None = None) -> dict:
    state = state if isinstance(state, dict) else {}
    config = {}
    for field in _STATEFUL_REQUEST_FIELDS:
        if field in payload and payload[field] is not None:
            config[field] = payload[field]
            continue
        if field in state and state[field] is not None:
            config[field] = state[field]
    return config


def _validate_provider_request(provider_id: str, request_config: dict):
    if not request_config.get("tools"):
        return
    if tool_request_supported(provider_id, request_config):
        return
    raise RuntimeError(unsupported_tool_message(provider_id))


def _chat_payload_from_request(payload: dict, provider_id: str) -> tuple[list, dict]:
    state_key, state = _load_state(payload)
    stored_messages = list(state.get("messages") or [])
    incoming_messages = _input_to_messages(payload)
    messages = _merge_messages(stored_messages, incoming_messages)
    request_config = _request_config_from_payload(payload, state)

    if provider_id == "zai":
        # Z.ai drops system/tool messages in its own adapter, so keep the request shape
        # conservative and let the provider decide what it can honor.
        pass

    chat_payload = dict(payload)
    chat_payload.pop("input", None)
    chat_payload["messages"] = messages
    chat_payload["stream"] = False

    for field, value in request_config.items():
        chat_payload[field] = value

    return messages, {
        "state_key": state_key,
        "stored_state": state,
        "chat_payload": chat_payload,
        "request_config": request_config,
    }


def _assistant_message_from_result(result: dict) -> dict:
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    content, pseudo_tool_calls = _extract_pseudo_tool_calls(message.get("content"))
    reasoning = _content_text(message.get("reasoning_content")).strip()
    tool_calls = (
        message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    )
    if not tool_calls:
        tool_calls = pseudo_tool_calls

    if tool_calls:
        assistant_message = {"role": "assistant", "content": ""}
        hidden_text = content or reasoning
        if hidden_text:
            assistant_message["reasoning_content"] = hidden_text
        assistant_message["tool_calls"] = tool_calls
        return assistant_message

    assistant_message = {"role": "assistant", "content": content}
    if reasoning:
        assistant_message["reasoning_content"] = reasoning
    return assistant_message


def _tool_calls_from_result(result: dict) -> list:
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        return tool_calls
    _, pseudo_tool_calls = _extract_pseudo_tool_calls(message.get("content"))
    return pseudo_tool_calls


def _output_items_from_result(result: dict) -> list:
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    content, pseudo_tool_calls = _extract_pseudo_tool_calls(message.get("content"))
    tool_calls = _tool_calls_from_result(result)
    if not tool_calls:
        tool_calls = pseudo_tool_calls

    output = []
    if content and not tool_calls:
        output.append(
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        )

    for tool_call in tool_calls:
        function = (
            tool_call.get("function")
            if isinstance(tool_call.get("function"), dict)
            else {}
        )
        call_id = (
            str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
            or f"call_{uuid.uuid4().hex}"
        )
        item_id = f"fc_{uuid.uuid4().hex}"
        arguments = (
            function.get("arguments") if function else tool_call.get("arguments")
        )
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


def _chat_completion_from_result(
    result: dict, response_id: str, previous_response_id: str, payload: dict
) -> dict:
    created_at = _now()
    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    content, pseudo_tool_calls = _extract_pseudo_tool_calls(message.get("content"))
    tool_calls = _tool_calls_from_result(result)
    if not tool_calls:
        tool_calls = pseudo_tool_calls
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    finish_reason = ((choices[0] or {}).get("finish_reason")) or (
        "tool_calls" if tool_calls else "stop"
    )
    reasoning_text = _content_text(message.get("reasoning_content")).strip()
    if tool_calls and content:
        reasoning_text = content

    response = {
        "id": response_id,
        "object": "chat.completion",
        "created": created_at,
        "model": result.get("model") or payload.get("model") or "",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "" if tool_calls else content,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                    **({"reasoning_content": reasoning_text} if reasoning_text else {}),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
        "conversation_id": response_id,
        "response_id": response_id,
        "previous_response_id": previous_response_id or None,
    }

    instructions = payload.get("instructions")
    if instructions is not None:
        response["instructions"] = instructions

    metadata = payload.get("metadata")
    if metadata is not None:
        response["metadata"] = metadata

    return response


def _response_usage_from_result(result: dict) -> dict:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(
        usage.get("completion_tokens") or usage.get("output_tokens") or 0
    )
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": total_tokens,
    }


def _output_text_from_items(output_items: list) -> str:
    texts = []
    for item in output_items or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if text:
                    texts.append(str(text))
    return "".join(texts)


def _response_api_from_result(
    result: dict, response_id: str, previous_response_id: str, payload: dict
) -> dict:
    output = _output_items_from_result(result)
    request_tools = (
        payload.get("tools") if isinstance(payload.get("tools"), list) else []
    )
    response = {
        "id": response_id,
        "object": "response",
        "created_at": _now(),
        "status": "completed",
        "background": False,
        "error": None,
        "incomplete_details": None,
        "instructions": payload.get("instructions"),
        "model": result.get("model") or payload.get("model") or "",
        "output": output,
        "output_text": _output_text_from_items(output),
        "parallel_tool_calls": payload.get("parallel_tool_calls", True),
        "previous_response_id": previous_response_id or None,
        "store": payload.get("store", True),
        "tool_choice": payload.get("tool_choice", "auto"),
        "tools": request_tools,
        "usage": _response_usage_from_result(result),
    }

    optional_fields = (
        "max_output_tokens",
        "metadata",
        "reasoning",
        "temperature",
        "text",
        "top_p",
        "truncation",
        "user",
    )
    for field in optional_fields:
        if field in payload and payload[field] is not None:
            response[field] = payload[field]

    if "reasoning" not in response and payload.get("reasoning_effort") is not None:
        response["reasoning"] = {"effort": payload.get("reasoning_effort")}

    return response


def _tool_call_delta(tool_call: dict, index: int) -> dict:
    function = (
        tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    )
    return {
        "index": index,
        "id": str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
        or f"call_{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": str(function.get("name") or tool_call.get("name") or ""),
            "arguments": str(
                function.get("arguments") if function else tool_call.get("arguments")
            ).strip()
            or "{}",
        },
    }


def _stream_chunks_from_result(result: dict):
    response_id = result.get("id") or f"chatcmpl_{uuid.uuid4().hex}"
    created = int(result.get("created") or _now())
    model = result.get("model") or ""
    builder = OpenAIStreamBuilder(response_id, model)
    builder.created = created

    choices = result.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    content, pseudo_tool_calls = _extract_pseudo_tool_calls(message.get("content"))
    tool_calls = _tool_calls_from_result(result)
    if not tool_calls:
        tool_calls = pseudo_tool_calls
    reasoning = _content_text(message.get("reasoning_content")).strip()

    if reasoning:
        for chunk in builder.reasoning(reasoning):
            yield chunk

    if tool_calls:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
        yield openai_chunk(
            response_id,
            model,
            created,
            {
                "tool_calls": [
                    _tool_call_delta(tool_call, index)
                    for index, tool_call in enumerate(tool_calls)
                ],
            },
        )

    if content and not tool_calls:
        for chunk in builder.content(content):
            yield chunk
    elif not reasoning and not tool_calls and not builder.role_sent:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk

    finish_reason = ((choices[0] or {}).get("finish_reason")) or (
        "tool_calls" if tool_calls else "stop"
    )
    yield builder.finish(finish_reason=finish_reason)


def complete_response(
    provider_id: str,
    credentials: dict,
    payload: dict,
    response_format: str = "chat",
):
    previous_response_id = _session_key(payload)
    messages, context = _chat_payload_from_request(payload, provider_id)
    _validate_provider_request(provider_id, context.get("request_config") or {})
    chat_payload = context["chat_payload"]
    result, meta = complete_non_stream(provider_id, credentials, chat_payload)
    result = _normalize_result_tool_calls(result, context.get("request_config") or {})

    response_id = f"resp_{uuid.uuid4().hex}"
    if str(response_format or "chat").strip().lower() in {"response", "responses"}:
        response = _response_api_from_result(
            result, response_id, previous_response_id, chat_payload
        )
    else:
        response = _chat_completion_from_result(
            result, response_id, previous_response_id, payload
        )
    assistant_message = _assistant_message_from_result(result)

    if payload.get("store", True) is not False:
        next_messages = list(messages)
        if assistant_message:
            next_messages.append(assistant_message)
        request_config = dict(context.get("request_config") or {})
        stored_response = (
            response
            if str(response_format or "chat").strip().lower()
            in {"response", "responses"}
            else _response_api_from_result(
                result, response_id, previous_response_id, chat_payload
            )
        )
        _save_state(
            response_id,
            {
                "messages": next_messages,
                "provider": provider_id,
                "model": response.get("model") or payload.get("model") or "",
                "previous_response_id": previous_response_id,
                "response": stored_response,
                **request_config,
            },
        )

    meta = dict(meta or {})
    meta.update(
        {
            "provider": provider_id,
            "response_id": response_id,
            "previous_response_id": previous_response_id,
            "message_count": len(messages),
            "output_text_length": len(
                _content_text(
                    (result.get("choices") or [{}])[0].get("message", {}).get("content")
                ).strip()
            ),
            "tool_call_count": len(_tool_calls_from_result(result)),
        }
    )

    debug_log("responses_complete", **meta)
    return response, meta


def _response_created_snapshot(response: dict) -> dict:
    snapshot = dict(response)
    snapshot["status"] = "in_progress"
    snapshot["output"] = []
    snapshot["output_text"] = ""
    return snapshot


def _stream_response_api_events(response: dict):
    response_id = str(response.get("id") or "")
    yield _event("response.created", response=_response_created_snapshot(response))

    for output_index, item in enumerate(response.get("output") or []):
        if not isinstance(item, dict):
            continue

        item_id = str(item.get("id") or "")
        in_progress_item = dict(item)
        if in_progress_item.get("status") == "completed":
            in_progress_item["status"] = "in_progress"
        if in_progress_item.get("type") == "message":
            in_progress_item["content"] = []
        elif in_progress_item.get("type") == "function_call":
            in_progress_item["arguments"] = ""
        yield _event(
            "response.output_item.added",
            response_id=response_id,
            output_index=output_index,
            item=in_progress_item,
        )

        if item.get("type") == "message":
            for content_index, part in enumerate(item.get("content") or []):
                if not isinstance(part, dict):
                    continue
                yield _event(
                    "response.content_part.added",
                    response_id=response_id,
                    item_id=item_id,
                    output_index=output_index,
                    content_index=content_index,
                    part={**part, "text": ""}
                    if part.get("type") == "output_text"
                    else part,
                )
                if part.get("type") == "output_text":
                    yield _event(
                        "response.output_text.delta",
                        response_id=response_id,
                        item_id=item_id,
                        output_index=output_index,
                        content_index=content_index,
                        delta=str(part.get("text") or ""),
                    )
                yield _event(
                    "response.content_part.done",
                    response_id=response_id,
                    item_id=item_id,
                    output_index=output_index,
                    content_index=content_index,
                    part=part,
                )

        if item.get("type") == "function_call":
            arguments = str(item.get("arguments") or "{}")
            yield _event(
                "response.function_call_arguments.delta",
                response_id=response_id,
                item_id=item_id,
                output_index=output_index,
                delta=arguments,
            )
            yield _event(
                "response.function_call_arguments.done",
                response_id=response_id,
                item_id=item_id,
                output_index=output_index,
                arguments=arguments,
            )

        yield _event(
            "response.output_item.done",
            response_id=response_id,
            output_index=output_index,
            item=item,
        )

    yield _event("response.completed", response=response)


def stream_response_events(
    provider_id: str,
    credentials: dict,
    payload: dict,
    response_format: str = "chat",
):
    response, meta = complete_response(
        provider_id, credentials, payload, response_format=response_format
    )
    debug_log(
        "responses_stream",
        provider=provider_id,
        response_id=response["id"],
        tool_call_count=meta.get("tool_call_count", 0),
        response_format=response_format,
    )
    if str(response_format or "chat").strip().lower() in {"response", "responses"}:
        for event in _stream_response_api_events(response):
            yield event
        return

    result = {
        "id": response["id"],
        "created": response.get("created"),
        "model": response.get("model"),
        "choices": response.get("choices"),
    }
    for chunk in _stream_chunks_from_result(result):
        yield chunk
