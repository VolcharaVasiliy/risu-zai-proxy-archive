import sys, os, json
sys.path.insert(0, "py")
os.environ["LM_ARENA_COOKIE_FILE"] = r"C:\Users\gamer\Desktop\lmarena-cookie.txt"
import lmarena_proxy as lp

# Load cookie header from the cookie jar file
ck = json.load(open(r"C:\Users\gamer\Desktop\lmarena-cookie.txt", encoding="utf-8"))
cookie = "; ".join(f"{c['name']}={c['value']}" for c in ck if c.get("name"))

payload = {
    "model": "gpt-5.2",
    "messages": [{"role": "user", "content": "Say hello in exactly three words."}],
    "stream": True,
}

print("=== non-stream ===")
try:
    text, meta = lp.complete_non_stream(cookie, payload)
    print("RESPONSE:", repr(text[:500]))
    print("META:", meta)
except Exception as e:
    print("ERROR:", repr(e))
