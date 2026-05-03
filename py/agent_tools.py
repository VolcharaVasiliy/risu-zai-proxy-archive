import copy
import json
import os
import re
import uuid
from typing import Any

NATIVE_TOOL_PROVIDERS = {"inflection", "uncloseai"}
_AGENT_TOOL_MODE_ENV = "AGENT_TOOL_MODE"
_TOOL_SCHEMA_MAX_CHARS_ENV = "AGENT_TOOL_SCHEMA_MAX_CHARS"

_TOOL_CALL_LINE_RE = re.compile(
    r"^\s*tool_call\s*:\s*(?P<name>[A-Za-z0-9_.:-]+)(?:\s+for\s+(?P<args>.*))?\s*$",
    re.IGNORECASE,
)
_TOOL_WAIT_RE = re.compile(
    r"^\s*\(?\s*wait(?:ing)?\s+for\s+tool\s+output.*\)?\s*$", re.IGNORECASE
)
_CODE_FENCE_RE = re.compile(
    r"```(?:json|javascript|js)?\s*(?P<body>.*?)```", re.IGNORECASE | re.DOTALL
)
_TOOL_TAG_RE = re.compile(
    r"<tool_calls?>\s*(?P<body>.*?)\s*</tool_calls?>", re.IGNORECASE | re.DOTALL
)
_SHELL_TOOL_NAMES = {"bash", "shell", "powershell", "pwsh", "cmd", "terminal"}
_PATH_TOOL_NAMES = {"ls", "list", "read_file", "read", "cat", "open", "image"}


TOOL_PROTOCOL_HEADER = """You are connected to an OpenAI-compatible agent runtime with client-side tools.

Important tool rules:
- The client executes tools. You must not pretend that you executed a command, read a file, opened a URL, used an MCP server, or changed code yourself.
- When a tool is useful, request it with the exact tool name from the list below.
- When you request a tool, your whole assistant response must be valid JSON and nothing else.
- Use this exact shape for one or more tool calls:
  {"tool_calls":[{"name":"exact_tool_name","arguments":{"arg":"value"}}]}
- If the client disabled parallel calls, request only one tool call at a time.
- After a tool result appears in the conversation, use that result to continue. If more information is needed, request another tool. Otherwise produce the final answer normally.
- If no listed tool is needed, answer normally without JSON.
- Never write shell commands or MCP instructions as plain text when a matching tool is available; call the tool instead.
""".strip()


def _env_int(
    name: str, default: int, minimum: int = 1024, maximum: int = 200_000
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _tool_mode() -> str:
    return os.environ.get(_AGENT_TOOL_MODE_ENV, "auto").strip().lower() or "auto"


def provider_has_native_tools(provider_id: str) -> bool:
    return str(provider_id or "").strip().lower() in NATIVE_TOOL_PROVIDERS


def request_tools(payload_or_config: dict | None) -> list:
    tools = (payload_or_config or {}).get("tools")
    return tools if isinstance(tools, list) and tools else []


def request_has_tools(payload_or_config: dict | None) -> bool:
    return bool(request_tools(payload_or_config))


def should_use_prompt_tool_shim(
    provider_id: str, payload_or_config: dict | None
) -> bool:
    if not request_has_tools(payload_or_config):
        return False

    mode = _tool_mode()
    if mode in {"off", "disable", "disabled", "none", "false", "0", "native"}:
        return False
    if mode in {"force", "forced", "prompt", "prompt-all", "shim", "synthetic"}:
        return True
    if provider_has_native_tools(provider_id):
        return False
    return True


def tool_request_supported(provider_id: str, payload_or_config: dict | None) -> bool:
    if not request_has_tools(payload_or_config):
        return True
    return provider_has_native_tools(provider_id) or should_use_prompt_tool_shim(
        provider_id, payload_or_config
    )


def unsupported_tool_message(provider_id: str) -> str:
    return (
        f"Provider '{provider_id}' is not configured for native tool calls and the prompt tool shim is disabled. "
        f"Set {_AGENT_TOOL_MODE_ENV}=auto to enable OpenAI-compatible synthetic tool calls, "
        "or use a native tool provider such as pi-api or uncloseai-*."
    )


def request_config_from_payload(payload: dict | None) -> dict:
    payload = payload or {}
    config = {}
    for key in ("tools", "tool_choice", "parallel_tool_calls"):
        if key in payload and payload[key] is not None:
            config[key] = payload[key]
    return config


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type in {"text", "input_text", "output_text"}:
                text = item.get("text")
                if text:
                    parts.append(str(text))
                continue
            if item_type in {"image_url", "input_image"}:
                image = item.get("image_url")
                if isinstance(image, dict):
                    image = image.get("url")
                image = image or item.get("file_url") or item.get("file_id")
                parts.append(f"[image: {image}]" if image else "[image]")
                continue
            if item_type in {"input_file", "file"}:
                filename = item.get("filename") or item.get("name") or "file"
                file_ref = (
                    item.get("file_url")
                    or item.get("file_id")
                    or item.get("file_data")
                    or ""
                )
                parts.append(f"[file: {filename}] {str(file_ref)[:200]}".strip())
                continue
        return "\n".join(part for part in parts if part)
    return str(content)


def _tool_name(tool: dict) -> str:
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(function.get("name") or tool.get("name") or "").strip()


def _tool_description(tool: dict) -> str:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(function.get("description") or tool.get("description") or "").strip()


def _tool_parameters(tool: dict) -> Any:
    function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return (
        function.get("parameters")
        if "parameters" in function
        else tool.get("parameters")
    )


def _tool_prompt_items(tools: list) -> list:
    items = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = _tool_name(tool)
        if not name:
            continue
        item = {
            "name": name,
            "description": _tool_description(tool),
            "parameters": _tool_parameters(tool)
            or {"type": "object", "properties": {}},
        }
        items.append(item)
    return items


def _tool_choice_instruction(tool_choice: Any, parallel_tool_calls: Any) -> str:
    lines = []
    if tool_choice is None or tool_choice == "auto":
        lines.append(
            "Tool choice: auto. Call tools only when they are useful for the task."
        )
    elif tool_choice == "none":
        lines.append("Tool choice: none. Do not call tools; answer directly.")
    elif tool_choice == "required":
        lines.append(
            "Tool choice: required. You must call at least one listed tool before giving a final answer."
        )
    elif isinstance(tool_choice, dict):
        function = (
            tool_choice.get("function")
            if isinstance(tool_choice.get("function"), dict)
            else {}
        )
        name = str(function.get("name") or tool_choice.get("name") or "").strip()
        if name:
            lines.append(
                f"Tool choice: required function `{name}`. Your next tool call must use this exact name."
            )
    else:
        lines.append(f"Tool choice: {tool_choice}.")

    if parallel_tool_calls is False:
        lines.append(
            "Parallel tool calls: disabled. Request at most one tool call in each assistant turn."
        )
    elif parallel_tool_calls is True:
        lines.append(
            "Parallel tool calls: enabled. You may request multiple independent tool calls in one JSON response."
        )

    return "\n".join(lines)


def build_tool_protocol_prompt(request_config: dict | None) -> str:
    request_config = request_config or {}
    tools = _tool_prompt_items(request_tools(request_config))
    schema_text = json.dumps(tools, ensure_ascii=False, indent=2)
    max_chars = _env_int(_TOOL_SCHEMA_MAX_CHARS_ENV, default=60_000)
    if len(schema_text) > max_chars:
        schema_text = (
            schema_text[:max_chars]
            + "\n... [tool schema truncated by proxy; use only visible tool names and schemas]"
        )

    return (
        f"{TOOL_PROTOCOL_HEADER}\n\n"
        f"{_tool_choice_instruction(request_config.get('tool_choice', 'auto'), request_config.get('parallel_tool_calls'))}\n\n"
        f"Available tools:\n{schema_text}"
    ).strip()


def _format_tool_calls_for_history(tool_calls: Any) -> str:
    if not isinstance(tool_calls, list) or not tool_calls:
        return ""
    compact = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = (
            call.get("function") if isinstance(call.get("function"), dict) else {}
        )
        compact.append(
            {
                "id": call.get("id") or call.get("call_id"),
                "name": function.get("name") or call.get("name"),
                "arguments": function.get("arguments")
                if "arguments" in function
                else call.get("arguments"),
            }
        )
    if not compact:
        return ""
    return "[assistant requested tool calls]\n" + json.dumps(
        compact, ensure_ascii=False
    )


def _normalize_messages_for_prompt_tools(messages: list) -> list:
    normalized = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower() or "user"
        content = _content_text(message.get("content")).strip()

        if role in {"system", "developer"}:
            if content:
                normalized.append(
                    {"role": "user", "content": f"[{role} instruction]\n{content}"}
                )
            continue

        if role in {"tool", "function"}:
            call_id = str(
                message.get("tool_call_id")
                or message.get("call_id")
                or message.get("id")
                or ""
            ).strip()
            name = str(message.get("name") or "").strip()
            label_parts = ["tool result"]
            if name:
                label_parts.append(f"name={name}")
            if call_id:
                label_parts.append(f"call_id={call_id}")
            normalized.append(
                {"role": "user", "content": f"[{'; '.join(label_parts)}]\n{content}"}
            )
            continue

        if role == "assistant":
            history_parts = []
            if content:
                history_parts.append(content)
            tool_history = _format_tool_calls_for_history(message.get("tool_calls"))
            if tool_history:
                history_parts.append(tool_history)
            normalized.append(
                {"role": "assistant", "content": "\n\n".join(history_parts)}
            )
            continue

        if role != "user":
            role = "user"
            if content:
                content = f"[{role} message]\n{content}"
        normalized.append({"role": role, "content": content})

    return normalized


def prepare_prompt_tool_payload(
    payload: dict, provider_id: str, request_config: dict | None = None
) -> dict:
    request_config = (
        request_config_from_payload(payload)
        if request_config is None
        else dict(request_config or {})
    )
    prepared = copy.deepcopy(payload)
    messages = (
        prepared.get("messages") if isinstance(prepared.get("messages"), list) else []
    )
    prepared["messages"] = [
        {"role": "user", "content": build_tool_protocol_prompt(request_config)},
        *_normalize_messages_for_prompt_tools(messages),
    ]

    # The upstream chat-only providers do not understand OpenAI tool schemas. The
    # prompt above is the transport protocol, and this proxy converts the text
    # response back into structured OpenAI tool calls for the client.
    prepared.pop("tools", None)
    prepared.pop("tool_choice", None)
    prepared.pop("parallel_tool_calls", None)
    prepared["_agent_tool_shim"] = {"mode": "prompt", "provider": provider_id}
    return prepared


def _available_tools(request_config: dict | None) -> list[dict]:
    return [
        tool
        for tool in request_tools(request_config)
        if isinstance(tool, dict) and _tool_name(tool)
    ]


def _available_name_map(request_config: dict | None) -> dict[str, str]:
    mapping = {}
    for tool in _available_tools(request_config):
        name = _tool_name(tool)
        mapping[name] = name
        mapping[name.lower()] = name
        mapping[_name_key(name)] = name
    return mapping


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _resolve_tool_name(name: str, request_config: dict | None) -> str:
    name = str(name or "").strip()
    mapping = _available_name_map(request_config)
    if not mapping:
        return name
    if name in mapping:
        return mapping[name]
    if name.lower() in mapping:
        return mapping[name.lower()]
    key = _name_key(name)
    if key in mapping:
        return mapping[key]
    return ""


def _arguments_json(arguments: Any) -> str:
    if arguments is None:
        return "{}"
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return "{}"
        try:
            parsed = json.loads(text)
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return json.dumps(
                {"input": text}, ensure_ascii=False, separators=(",", ":")
            )
    if isinstance(arguments, (dict, list)):
        return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"input": arguments}, ensure_ascii=False, separators=(",", ":"))


def _tool_call(
    name: str, arguments: Any, request_config: dict | None, call_id: str = ""
) -> dict | None:
    resolved = _resolve_tool_name(name, request_config)
    if not resolved:
        tools = _available_tools(request_config)
        if len(tools) == 1 and not name:
            resolved = _tool_name(tools[0])
        else:
            return None

    return {
        "id": call_id or f"call_{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": resolved,
            "arguments": _arguments_json(arguments),
        },
    }


def _schema_property_names(tool: dict) -> set[str]:
    parameters = _tool_parameters(tool)
    if not isinstance(parameters, dict):
        return set()
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return set()
    return {str(key) for key in properties.keys()}


def _bare_json_matches_single_tool(value: Any, request_config: dict | None) -> bool:
    tools = _available_tools(request_config)
    if len(tools) != 1 or not isinstance(value, dict):
        return False

    tool_choice = (request_config or {}).get("tool_choice")
    if tool_choice == "required" or isinstance(tool_choice, dict):
        return True

    property_names = _schema_property_names(tools[0])
    if not property_names:
        return False
    return bool(property_names.intersection(str(key) for key in value.keys()))


def _calls_from_value(
    value: Any, request_config: dict | None, allow_bare_arguments: bool = False
) -> list[dict]:
    if isinstance(value, list):
        calls = []
        for item in value:
            calls.extend(
                _calls_from_value(item, request_config, allow_bare_arguments=False)
            )
        return _limit_parallel_calls(calls, request_config)

    if not isinstance(value, dict):
        return []

    if isinstance(value.get("tool_calls"), list):
        calls = []
        for item in value.get("tool_calls") or []:
            calls.extend(
                _calls_from_value(item, request_config, allow_bare_arguments=False)
            )
        return _limit_parallel_calls(calls, request_config)

    if isinstance(value.get("calls"), list):
        calls = []
        for item in value.get("calls") or []:
            calls.extend(
                _calls_from_value(item, request_config, allow_bare_arguments=False)
            )
        return _limit_parallel_calls(calls, request_config)

    if "tool_call" in value:
        nested = value.get("tool_call")
        if isinstance(nested, list):
            calls = []
            for item in nested:
                calls.extend(
                    _calls_from_value(item, request_config, allow_bare_arguments=False)
                )
            return _limit_parallel_calls(calls, request_config)
        return _calls_from_value(nested, request_config, allow_bare_arguments=False)

    function = value.get("function") if isinstance(value.get("function"), dict) else {}
    name = str(
        function.get("name") or value.get("name") or value.get("tool_name") or ""
    ).strip()
    if name:
        arguments = (
            function.get("arguments")
            if "arguments" in function
            else value.get(
                "arguments",
                value.get("args", value.get("parameters", value.get("input"))),
            )
        )
        call = _tool_call(
            name,
            arguments,
            request_config,
            call_id=str(value.get("id") or value.get("call_id") or "").strip(),
        )
        return [call] if call else []

    if allow_bare_arguments and _bare_json_matches_single_tool(value, request_config):
        call = _tool_call("", value, request_config)
        return [call] if call else []

    return []


def _limit_parallel_calls(calls: list[dict], request_config: dict | None) -> list[dict]:
    calls = [call for call in calls if call]
    if (request_config or {}).get("parallel_tool_calls") is False and len(calls) > 1:
        return calls[:1]
    return calls


def _pseudo_tool_call_arguments(name: str, args_text: str) -> str:
    tool_name = str(name or "").strip().lower()
    text = str(args_text or "").strip()

    if tool_name in _SHELL_TOOL_NAMES:
        return json.dumps({"command": text}, ensure_ascii=False, separators=(",", ":"))

    if tool_name in _PATH_TOOL_NAMES:
        lowered = text.lower()
        for prefix, key in (
            ("absolute_path ", "absolute_path"),
            ("relative_path ", "relative_path"),
            ("path ", "path"),
            ("file ", "file"),
        ):
            if lowered.startswith(prefix):
                return json.dumps(
                    {key: text[len(prefix) :].strip()},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        if not text:
            return "{}"
        return json.dumps({"path": text}, ensure_ascii=False, separators=(",", ":"))

    if not text:
        return "{}"

    try:
        parsed = json.loads(text)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return json.dumps({"input": text}, ensure_ascii=False, separators=(",", ":"))


def _extract_pseudo_tool_calls(
    text: str, request_config: dict | None
) -> tuple[str, list[dict]]:
    plain_lines = []
    calls = []
    for line in str(text or "").splitlines():
        tool_match = _TOOL_CALL_LINE_RE.match(line)
        if tool_match:
            name = str(tool_match.group("name") or "").strip()
            args_text = str(tool_match.group("args") or "").strip()
            call = _tool_call(
                name, _pseudo_tool_call_arguments(name, args_text), request_config
            )
            if call:
                calls.append(call)
                continue

        if _TOOL_WAIT_RE.match(line):
            continue
        plain_lines.append(line)

    return "\n".join(plain_lines).strip(), _limit_parallel_calls(calls, request_config)


def _json_candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    stripped = text.strip()
    if stripped:
        candidates.append((stripped, stripped))

    for match in _TOOL_TAG_RE.finditer(text):
        body = match.group("body").strip()
        if body:
            candidates.append((match.group(0), body))

    for match in _CODE_FENCE_RE.finditer(text):
        body = match.group("body").strip()
        if body:
            candidates.append((match.group(0), body))

    for raw in _balanced_json_substrings(text):
        lowered = raw.lower()
        if "tool" in lowered or "arguments" in lowered or "args" in lowered:
            candidates.append((raw, raw))

    seen = set()
    unique = []
    for original, body in candidates:
        key = (original, body)
        if key in seen:
            continue
        seen.add(key)
        unique.append((original, body))
    return unique[:40]


def _balanced_json_substrings(text: str) -> list[str]:
    results = []
    length = len(text)
    for start, char in enumerate(text):
        if char not in "[{":
            continue
        stack = ["}" if char == "{" else "]"]
        in_string = False
        escape = False
        for index in range(start + 1, length):
            current = text[index]
            if in_string:
                if escape:
                    escape = False
                elif current == "\\":
                    escape = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
                continue
            if current in "[{":
                stack.append("}" if current == "{" else "]")
                continue
            if current in "}]":
                if not stack or current != stack[-1]:
                    break
                stack.pop()
                if not stack:
                    results.append(text[start : index + 1])
                    break
    return results


def extract_tool_calls_from_content(
    content: Any, request_config: dict | None = None
) -> tuple[str, list[dict]]:
    text = _content_text(content).strip()
    if not text:
        return "", []

    for original, body in _json_candidates(text):
        try:
            parsed = json.loads(body)
        except Exception:
            continue
        calls = _calls_from_value(
            parsed, request_config, allow_bare_arguments=(body.strip() == text)
        )
        if calls:
            remaining = text.replace(original, "", 1).strip()
            return remaining, calls

    return _extract_pseudo_tool_calls(text, request_config)


def _normalized_existing_tool_calls(
    tool_calls: Any, request_config: dict | None = None
) -> list[dict]:
    if not isinstance(tool_calls, list):
        return []
    normalized = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = (
            call.get("function") if isinstance(call.get("function"), dict) else {}
        )
        name = str(function.get("name") or call.get("name") or "").strip()
        arguments = (
            function.get("arguments")
            if "arguments" in function
            else call.get("arguments")
        )
        normalized_call = _tool_call(
            name,
            arguments,
            request_config if request_has_tools(request_config) else None,
            call_id=str(call.get("id") or call.get("call_id") or "").strip(),
        )
        if normalized_call:
            normalized.append(normalized_call)
    return _limit_parallel_calls(normalized, request_config)


def normalize_tool_result(
    result: dict, request_config: dict | None = None
) -> tuple[dict, int]:
    if not isinstance(result, dict):
        return result, 0
    choices = result.get("choices") if isinstance(result.get("choices"), list) else []
    if not choices:
        return result, 0

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = (
        first_choice.get("message")
        if isinstance(first_choice.get("message"), dict)
        else {}
    )
    if not message:
        return result, 0

    existing_calls = _normalized_existing_tool_calls(
        message.get("tool_calls"), request_config
    )
    remaining_text = ""
    tool_calls = existing_calls
    if not tool_calls and request_has_tools(request_config):
        remaining_text, tool_calls = extract_tool_calls_from_content(
            message.get("content"), request_config
        )

    if not tool_calls:
        return result, 0

    normalized_result = dict(result)
    normalized_choices = list(choices)
    normalized_choice = dict(first_choice)
    normalized_message = dict(message)
    normalized_message["content"] = ""
    normalized_message["tool_calls"] = tool_calls
    if remaining_text:
        existing_reasoning = _content_text(
            normalized_message.get("reasoning_content")
        ).strip()
        normalized_message["reasoning_content"] = (
            f"{existing_reasoning}\n{remaining_text}".strip()
        )
    normalized_choice["message"] = normalized_message
    normalized_choice["finish_reason"] = "tool_calls"
    normalized_choices[0] = normalized_choice
    normalized_result["choices"] = normalized_choices
    return normalized_result, len(tool_calls)


def tool_call_delta(tool_call: dict, index: int) -> dict:
    function = (
        tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    )
    arguments = (
        function.get("arguments")
        if "arguments" in function
        else tool_call.get("arguments")
    )
    if isinstance(arguments, (dict, list)):
        arguments_text = json.dumps(
            arguments, ensure_ascii=False, separators=(",", ":")
        )
    else:
        arguments_text = str(arguments or "").strip() or "{}"
    return {
        "index": index,
        "id": str(tool_call.get("id") or tool_call.get("call_id") or "").strip()
        or f"call_{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": str(function.get("name") or tool_call.get("name") or ""),
            "arguments": arguments_text,
        },
    }
