import json
import sys

import requests


BASE_URL = "http://127.0.0.1:3001"
MODEL = "uncloseai-gpt-oss"
REPORT_PATH = r"F:\REPORT.md"


def _print(label: str, value):
    print(f"{label}: {json.dumps(value, ensure_ascii=False)}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    first_body = {
        "model": MODEL,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Use the read tool immediately to inspect {REPORT_PATH}. "
                    "After receiving the tool result, summarize the beginning of the report in one sentence."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "Read a file by absolute path",
                    "parameters": {
                        "type": "object",
                        "properties": {"absolute_path": {"type": "string"}},
                        "required": ["absolute_path"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }

    first = requests.post(f"{BASE_URL}/v1/responses/chat/completions", json=first_body, timeout=120)
    first.raise_for_status()
    first_json = first.json()
    _print("first", first_json)

    tool_calls = (((first_json.get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or [])
    if not tool_calls:
        raise RuntimeError("First response did not contain tool_calls")

    call = tool_calls[0]
    if ((call.get("function") or {}).get("name") or "") != "read":
        raise RuntimeError(f"Unexpected tool name: {call}")

    arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
    if arguments.get("absolute_path") != REPORT_PATH:
        raise RuntimeError(f"Unexpected tool arguments: {arguments}")

    with open(REPORT_PATH, "r", encoding="utf-8", errors="replace") as handle:
        tool_output = "".join(handle.readlines()[:6])

    second_body = {
        "model": MODEL,
        "stream": False,
        "previous_response_id": first_json["response_id"],
        "messages": [
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": tool_output,
            }
        ],
    }

    second = requests.post(f"{BASE_URL}/v1/responses/chat/completions", json=second_body, timeout=120)
    second.raise_for_status()
    second_json = second.json()
    _print("second", second_json)

    second_choices = second_json.get("choices") or [{}]
    second_message = (second_choices[0] or {}).get("message") or {}
    second_text = str(second_message.get("content") or "").strip()
    second_finish = (second_choices[0] or {}).get("finish_reason") or ""

    if not second_text:
        raise RuntimeError("Second response did not contain assistant text")
    if second_finish != "stop":
        raise RuntimeError(f"Unexpected finish reason: {second_finish}")

    print("loop_test: ok")


if __name__ == "__main__":
    main()
