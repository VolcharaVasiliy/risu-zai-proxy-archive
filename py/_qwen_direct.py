import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

CREDS = json.load(open("credentials.json", encoding="utf-8"))

BASE = "https://chat.qwen.ai"

HEADERS_BASE = {
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Content-Type": "application/json",
    "x-accel-buffering": "no",
    "source": "web",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 YaBrowser/26.3.0.0 Safari/537.36",
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "YaBrowser";v="26.3", "Yowser";v="2.5"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Version": "0.2.83",
}


def headers(chat_id="", phase="create"):
    bx_ua = CREDS["QWEN_AI_BX_UA_CHAT"] if phase == "chat" else CREDS["QWEN_AI_BX_UA_CREATE"]
    h = dict(HEADERS_BASE)
    h["X-Request-Id"] = str(uuid.uuid4())
    h["bx-v"] = CREDS.get("QWEN_AI_BX_V", "2.5.37")
    h["Timezone"] = CREDS.get("QWEN_AI_TIMEZONE", "")
    if bx_ua:
        h["bx-ua"] = bx_ua
    if CREDS.get("QWEN_AI_BX_UMIDTOKEN"):
        h["bx-umidtoken"] = CREDS["QWEN_AI_BX_UMIDTOKEN"]
    if chat_id:
        h["Referer"] = f"{BASE}/c/{chat_id}"
    h["Cookie"] = CREDS["QWEN_AI_COOKIE"]
    return h


def create_chat(model_id="qwen3.7-max"):
    r = requests.post(
        f"{BASE}/api/v2/chats/new",
        headers=headers(phase="create"),
        json={
            "title": "OpenAI_API_Chat",
            "models": [model_id],
            "chat_mode": "normal",
            "chat_type": "t2t",
            "timestamp": int(time.time() * 1000),
            "project_id": "",
        },
        timeout=30,
    )
    print("CREATE STATUS:", r.status_code)
    print("CREATE BODY:", r.text[:400])
    data = r.json()
    chat_id = data.get("data", {}).get("id")
    print("CHAT_ID:", chat_id)
    return chat_id


def chat(chat_id, model_id="qwen3.7-max"):
    fid = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    now_s = int(time.time())
    body = {
        "stream": True,
        "version": "2.1",
        "incremental_output": True,
        "chatId": chat_id,
        "parentId": "",
        "chat_id": chat_id,
        "chat_mode": "normal",
        "model": model_id,
        "parent_id": None,
        "messages": [
            {
                "fid": fid,
                "id": None,
                "model": "",
                "parentId": None,
                "childrenIds": [child_id],
                "role": "user",
                "content": "Say OK",
                "user_action": "chat",
                "files": [],
                "timestamp": now_s,
                "models": [model_id],
                "chat_type": "t2t",
                "feature_config": {
                    "thinking_enabled": False,
                    "output_schema": "phase",
                    "research_mode": "normal",
                    "auto_thinking": False,
                    "thinking_mode": "Auto",
                    "thinking_format": "summary",
                    "auto_search": True,
                },
                "extra": {"meta": {"subChatType": "t2t"}},
                "sub_chat_type": "t2t",
                "parent_id": None,
            }
        ],
        "timestamp": now_s + 1,
    }
    r = requests.post(
        f"{BASE}/api/v2/chat/completions?chat_id={chat_id}",
        headers={**headers(chat_id, phase="chat"), "x-accel-buffering": "no"},
        json=body,
        timeout=60,
        stream=True,
    )
    print("CHAT STATUS:", r.status_code)
    print("CHAT HEADERS:", dict(list(r.headers.items())), file=sys.stderr)
    ctype = r.headers.get("Content-Type", "")
    if "json" in ctype and "text/event-stream" not in ctype:
        with open("_qwen_body.json", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("BODY SAVED to _qwen_body.json")
        r.close()
        return
    lines = []
    for i, raw in enumerate(r.iter_lines(decode_unicode=True)):
        if i >= 25:
            print("... (truncated)")
            break
        print(f"LINE[{i}]: {raw[:500]}")
        if raw and raw.startswith("data:") and raw[5:].strip() == "[DONE]":
            break
    r.close()


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3.7-max"
    cid = create_chat(model)
    if cid:
        chat(cid, model)