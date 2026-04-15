import json
import os
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


# Module constants
OWNED_BY = "Phind (phind.com)"
SUPPORTED_MODELS = ["phind-chat", "phind-search"]


def supports_model(model: str) -> bool:
    """Check if the model is supported by Phind provider."""
    return str(model or "").lower() in [m.lower() for m in SUPPORTED_MODELS]


def _get_nonce(cookie: str) -> str:
    """Fetches nonce from phindai.org page."""
    import re
    try:
        response = requests.get(
            "https://phindai.org/phind-chat/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Cookie": cookie
            },
            timeout=10
        )
        
        if response.status_code == 200:
            # Try multiple patterns
            patterns = [
                r'phindAjax\.nonce\s*=\s*["\']([^"\']+)["\']',
                r'"nonce"\s*:\s*"([^"]+)"',
                r'nonce["\']?\s*:\s*["\']([^"\']+)["\']'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response.text)
                if match:
                    return match.group(1)
        
        # If we can't get nonce, return empty (will use env var or fail)
        return ""
    except:
        return ""


def _select_endpoint(model: str) -> tuple:
    """
    Returns (endpoint_url, endpoint_type) based on model identifier.
    endpoint_type: "wordpress" (phindai.org uses WordPress AJAX)
    """
    # All models use the same WordPress AJAX endpoint
    return ("https://phindai.org/wp-admin/admin-ajax.php", "wordpress")



def _build_wordpress_request(payload: dict) -> dict:
    """
    Converts OpenAI messages to WordPress AJAX format.
    Returns dict with action, message, and nonce.
    """
    messages = payload.get("messages") or []
    if not messages:
        raise RuntimeError("Phind request requires at least one message")
    
    # Extract last user message
    message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            message = str(msg.get("content") or "")
            break
    
    if not message:
        raise RuntimeError("Phind request requires at least one user message")
    
    # WordPress AJAX format (form-urlencoded, not JSON)
    # Note: nonce needs to be extracted from the page or provided by user
    return {
        "action": "phind_ai_send",
        "message": message,
        "nonce": os.environ.get("PHIND_NONCE", ""),
        "user_ip": ""  # Optional, can be left empty
    }



def _headers(cookie: str) -> dict:
    """Constructs HTTP headers for WordPress AJAX request."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "*/*",
        "Origin": "https://phindai.org",
        "Referer": "https://phindai.org/phind-chat/",
        "X-Requested-With": "XMLHttpRequest",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin"
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def stream_chunks(credentials: dict, payload: dict):
    """
    Streams OpenAI-compatible chunks from Phind WordPress API.
    Yields OpenAI-format chunk dictionaries.
    """
    cookie = (credentials or {}).get("cookie", "")
    nonce = (credentials or {}).get("nonce", "")
    
    # If no nonce provided, try to fetch it
    if not nonce and cookie:
        nonce = _get_nonce(cookie)
    
    if not nonce:
        raise RuntimeError("Phind nonce required but not found")
    
    request_model = str(payload.get("model") or "phind-chat")
    endpoint_url, endpoint_type = _select_endpoint(request_model)
    
    # Build WordPress AJAX request
    request_body = _build_wordpress_request(payload)
    request_body["nonce"] = nonce
    
    debug_log("phind_chat_started", model=request_model, endpoint=endpoint_type, stream=True)
    
    # Convert to form-urlencoded format
    form_data = urlencode(request_body)
    
    # Make HTTP request
    response = requests.post(
        endpoint_url,
        headers=_headers(cookie),
        data=form_data,
        timeout=120,
        stream=False  # WordPress AJAX returns complete response, not SSE
    )
    
    # Check for authentication errors
    if response.status_code in {401, 403}:
        response.close()
        raise RuntimeError(f"Phind authentication failed: HTTP {response.status_code}")
    
    # Check for other errors
    if response.status_code != 200:
        body_preview = response.text[:300] if hasattr(response, 'text') else ""
        response.close()
        raise RuntimeError(f"Phind completion failed: HTTP {response.status_code} {body_preview}")
    
    # Parse response (WordPress returns JSON)
    try:
        result = response.json()
        response.close()
    except Exception as exc:
        response.close()
        raise RuntimeError(f"Phind response parse failed: {exc}")
    
    # Extract text from WordPress response
    # Response format: {"success": true, "data": {"response": "...", "time": "..."}}
    if not result.get("success"):
        error_msg = result.get("data", {}).get("message", "Unknown error")
        raise RuntimeError(f"Phind API error: {error_msg}")
    
    response_text = result.get("data", {}).get("response", "")
    if not response_text:
        debug_log("phind_empty_response", model=request_model)
    
    # Stream the response as chunks (simulate streaming)
    builder = OpenAIStreamBuilder("phind", request_model)
    
    # Split response into chunks for streaming effect
    chunk_size = 50
    for i in range(0, len(response_text), chunk_size):
        chunk_text = response_text[i:i+chunk_size]
        yield from builder.content(chunk_text)
    
    debug_log("phind_stream_done", model=request_model, provider="phind", content_length=len(response_text))
    yield builder.finish()



def complete_non_stream(credentials: dict, payload: dict):
    """
    Returns complete OpenAI-compatible response from Phind API.
    Returns tuple (result: dict, meta: dict).
    """
    # Buffer all chunks from streaming
    content_parts = []
    request_model = str(payload.get("model") or "phind-chat")
    
    for chunk in stream_chunks(credentials, payload):
        if chunk.get("choices") and len(chunk["choices"]) > 0:
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta:
                content_parts.append(delta["content"])
    
    # Build complete response
    full_content = "".join(content_parts)
    message = {
        "role": "assistant",
        "content": full_content
    }
    
    result = {
        "id": f"phind-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }
    
    meta = {
        "provider": "phind",
        "model": request_model,
        "content_length": len(full_content),
        "empty_content": not bool(full_content)
    }
    
    debug_log("phind_non_stream_done", **meta)
    return result, meta
