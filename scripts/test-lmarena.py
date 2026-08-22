import sys, os, json
sys.path.insert(0, "py")
cookie_file = os.environ.get("LM_ARENA_COOKIE_FILE", r"C:\Users\gamer\Desktop\lmarena-cookie.txt")
if not os.path.exists(cookie_file):
    print(f"LM Arena live test skipped: cookie file is missing: {cookie_file}")
    raise SystemExit(0)
os.environ["LM_ARENA_COOKIE_FILE"] = cookie_file
import lmarena_proxy as lp

# Load cookie header from the cookie jar file
ck = json.load(open(cookie_file, encoding="utf-8"))
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
