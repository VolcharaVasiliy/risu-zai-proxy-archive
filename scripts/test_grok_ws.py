import asyncio
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pydeps"))
import websockets

ROOT = os.path.join(os.path.dirname(__file__), "..")
CLEAR_FILE = os.path.join(ROOT, "grok_cf_clearance.json")
PROMPT = sys.argv[1] if len(sys.argv) > 1 else "Say hello in one word."


def load_cookie():
    with open(CLEAR_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["cookie"], data.get("cf_clearance")


def uid_from_cookie(cookie):
    m = re.search(r"x-userid=([0-9a-f-]+)", cookie)
    return m.group(1) if m else str(uuid.uuid4())


async def main():
    cookie, cf = load_cookie()
    uid = uid_from_cookie(cookie)
    url = f"wss://grok.com/ws/mgw/?uid={uid}"
    headers = {
        "Cookie": cookie,
        "Origin": "https://grok.com",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        ),
    }

    session_id = None
    response_text = []
    done = asyncio.Event()

    async with websockets.connect(url, additional_headers=headers, ping_interval=None) as ws:
        async def send(obj):
            await ws.send(json.dumps(obj))

        # session.create
        await send({
            "event": {
                "type": "session.create",
                "event_id": "evt_init_" + str(uuid.uuid4()),
                "session": {
                    "model": "fast",
                    "x_grok": {
                        "protocol_capabilities": ["conversation_attached", "custom_methods_v1"],
                        "use_chunk": True,
                        "enable_side_by_side": True,
                        "force_side_by_side": False,
                        "enable_image_generation": True,
                        "image_generation_count": 2,
                        "disable_text_follow_ups": False,
                        "disable_artifact": True,
                        "force_concise": False,
                    },
                },
            }
        })

        async def reader():
            nonlocal session_id
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        print("NONJSON:", raw[:200])
                        continue
                    ev = msg.get("event", {})
                    t = ev.get("type")
                    if t == "session.created":
                        session_id = msg.get("session_id")
                        print("session.created id=", session_id)
                        # attach handled by server (conversation.attached follows)
                    elif t == "conversation.attached":
                        print("conversation.attached", msg.get("conversation", {}).get("id"))
                        # now send user message
                        await send({
                            "session_id": session_id,
                            "event": {
                                "type": "conversation.item.create",
                                "event_id": "evt_msg_" + str(int(asyncio.get_event_loop().time() * 1000)),
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "x_grok": {
                                        "client_message_id": str(uuid.uuid4()),
                                        "input_chunks": [{"text": {"text": PROMPT}}],
                                    },
                                },
                            },
                        })
                        await send({
                            "session_id": session_id,
                            "event": {
                                "type": "response.create",
                                "event_id": "evt_resp_" + str(int(asyncio.get_event_loop().time() * 1000)),
                            },
                        })
                        print(">> sent message + response.create (no castle token)")
                    elif t == "response.chunk":
                        chunk = ev.get("chunk", {})
                        txt = chunk.get("text", {}).get("text")
                        if txt:
                            response_text.append(txt)
                    elif t == "response.done":
                        print("response.done status=", ev.get("response", {}).get("status"))
                        done.set()
                    elif t == "ping":
                        await send({"event": {"type": "pong", "event_id": ev.get("event_id")}})
                    elif t in ("error",):
                        print("ERROR EVENT:", json.dumps(ev)[:500])
                        done.set()
            except Exception as e:
                print("READER ERR:", e)
                done.set()

        rt = asyncio.create_task(reader())
        try:
            await asyncio.wait_for(done.wait(), timeout=90)
        except asyncio.TimeoutError:
            print("TIMEOUT")
        await rt

    print("\n=== RESPONSE ===")
    print("".join(response_text))


asyncio.run(main())
