import copy
import os
import re
from typing import Any

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log


TEXT_ITEM_TYPES = {"text", "input_text", "output_text"}
IMAGE_ITEM_TYPES = {"image_url", "input_image"}
FILE_ITEM_TYPES = {"input_file", "file"}
_NATIVE_IMAGE_PROVIDERS = {"google-ai-studio"}
_NATIVE_IMAGE_MODELS = {"uncloseai-qwen-vl"}
_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[^;,]+)?(?:;[^,]*)?;base64,(?P<data>.*)$", re.I | re.S
)


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 1000) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _mode() -> str:
    return (
        os.environ.get("MULTIMODAL_IMAGE_MODE")
        or os.environ.get("RISU_MULTIMODAL_IMAGE_MODE")
        or "auto"
    ).strip().lower() or "auto"


def _caption_api_key() -> str:
    for name in ("GOOGLE_AI_STUDIO_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def provider_accepts_native_images(provider_id: str, model: str = "") -> bool:
    provider = str(provider_id or "").strip().lower()
    request_model = str(model or "").strip().lower()
    return provider in _NATIVE_IMAGE_PROVIDERS or request_model in _NATIVE_IMAGE_MODELS


def _item_type(item: dict) -> str:
    return str((item or {}).get("type") or "").strip().lower()


def _image_url_value(item: dict) -> str:
    image = item.get("image_url")
    if isinstance(image, dict):
        image = image.get("url")
    return str(
        image or item.get("url") or item.get("file_url") or item.get("file_id") or ""
    ).strip()


def _is_image_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    item_type = _item_type(item)
    if item_type in IMAGE_ITEM_TYPES:
        return True
    if item_type in FILE_ITEM_TYPES:
        mime = str(item.get("mime_type") or item.get("media_type") or "").lower()
        if mime.startswith("image/"):
            return True
        file_data = str(item.get("file_data") or item.get("data") or "").strip()
        if file_data.startswith("data:image/"):
            return True
    return False


def _text_from_item(item: dict) -> str:
    item_type = _item_type(item)
    if item_type in TEXT_ITEM_TYPES:
        return str(item.get("text") or "")
    if item_type in FILE_ITEM_TYPES and not _is_image_item(item):
        filename = str(item.get("filename") or item.get("name") or "file").strip()
        file_url = str(
            item.get("file_url") or item.get("url") or item.get("file_id") or ""
        ).strip()
        if file_url:
            return f"[file: {filename}] {file_url}"
        file_data = str(item.get("file_data") or item.get("data") or "").strip()
        if file_data:
            return f"[file: {filename}] inline data ({len(file_data)} chars)"
        return f"[file: {filename}]"
    return ""


def _text_only_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""
    parts = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append(item)
            continue
        if isinstance(item, dict):
            text = _text_from_item(item).strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _image_placeholder(item: dict, index: int) -> str:
    mime = (
        str(item.get("mime_type") or item.get("media_type") or "image").strip()
        or "image"
    )
    url = _image_url_value(item)
    file_data = str(item.get("file_data") or item.get("data") or "").strip()

    if file_data:
        data_url = file_data if file_data.startswith("data:") else ""
        match = _DATA_URL_RE.match(data_url)
        if match:
            detected_mime = (match.group("mime") or mime or "image").strip()
            raw_data = re.sub(r"\s+", "", match.group("data") or "")
            approx_bytes = (len(raw_data) * 3) // 4 if raw_data else 0
            return (
                f"[Image {index}: inline {detected_mime}, about {approx_bytes} bytes]"
            )
        approx_bytes = (len(re.sub(r"\s+", "", file_data)) * 3) // 4
        return f"[Image {index}: inline {mime}, about {approx_bytes} bytes]"

    if url:
        if url.startswith("data:"):
            match = _DATA_URL_RE.match(url)
            if match:
                detected_mime = (match.group("mime") or mime or "image").strip()
                raw_data = re.sub(r"\s+", "", match.group("data") or "")
                approx_bytes = (len(raw_data) * 3) // 4 if raw_data else 0
                return f"[Image {index}: inline {detected_mime}, about {approx_bytes} bytes]"
            return f"[Image {index}: inline data URL]"
        if len(url) > 500:
            url = url[:497] + "..."
        return f"[Image {index}: {url}]"

    return f"[Image {index}: attached image]"


def _collect_images(messages: list) -> list[dict]:
    images = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if _is_image_item(item):
                images.append(item)
    return images


def request_has_images(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(_collect_images(payload.get("messages") or []))


def _caption_context(messages: list) -> str:
    chunks = []
    for message in (messages or [])[-8:]:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip() or "user"
        text = _text_only_from_content(message.get("content")).strip()
        if text:
            chunks.append(f"{role}: {text}")
    return "\n".join(chunks)[-6000:]


def _describe_images(images: list[dict], context: str) -> list[str]:
    mode = _mode()
    if mode in {"off", "none", "false", "0", "passthrough", "placeholder"}:
        return [""] * len(images)

    api_key = _caption_api_key()
    if not api_key:
        return [""] * len(images)

    try:
        try:
            from py import google_ai_studio_proxy
        except ImportError:
            import google_ai_studio_proxy
    except Exception as exc:
        debug_log("multimodal_caption_import_failed", error=str(exc))
        return [""] * len(images)

    descriptions = []
    for index, image in enumerate(images, start=1):
        try:
            description = google_ai_studio_proxy.describe_image_item(
                {"api_key": api_key}, image, context_text=context, index=index
            )
            descriptions.append(str(description or "").strip())
        except Exception as exc:
            debug_log("multimodal_caption_failed", image_index=index, error=str(exc))
            descriptions.append("")
    return descriptions


def _content_with_image_descriptions(
    content: Any, descriptions: list[str], state: dict
) -> Any:
    if isinstance(content, str) or not isinstance(content, list):
        return content

    parts = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append(item)
            continue
        if not isinstance(item, dict):
            continue

        if _is_image_item(item):
            state["image_index"] += 1
            index = state["image_index"]
            description = (
                descriptions[index - 1] if index - 1 < len(descriptions) else ""
            )
            placeholder = _image_placeholder(item, index)
            if description:
                parts.append(f"{placeholder}\nDescription: {description}")
            else:
                parts.append(placeholder)
            continue

        text = _text_from_item(item).strip()
        if text:
            parts.append(text)

    return "\n\n".join(part for part in parts if part)


def prepare_payload_for_provider(
    provider_id: str, credentials: dict | None, payload: dict
) -> dict:
    if not isinstance(payload, dict):
        return payload
    if payload.get("_multimodal_processed"):
        return payload

    request_model = str(payload.get("model") or "")
    if provider_accepts_native_images(provider_id, request_model):
        return payload

    mode = _mode()
    if mode in {"off", "none", "false", "0", "passthrough", "native"}:
        return payload

    messages = (
        payload.get("messages") if isinstance(payload.get("messages"), list) else []
    )
    images = _collect_images(messages)
    if not images:
        return payload

    max_images = _env_int("MULTIMODAL_MAX_IMAGES", default=8, minimum=0, maximum=64)
    capped_images = images[:max_images]
    descriptions = _describe_images(capped_images, _caption_context(messages))
    if len(descriptions) < len(images):
        descriptions.extend([""] * (len(images) - len(descriptions)))

    prepared = copy.deepcopy(payload)
    state = {"image_index": 0}
    prepared_messages = []
    for message in prepared.get("messages") or []:
        if not isinstance(message, dict):
            prepared_messages.append(message)
            continue
        updated = dict(message)
        updated["content"] = _content_with_image_descriptions(
            message.get("content"), descriptions, state
        )
        prepared_messages.append(updated)

    caption_count = sum(1 for description in descriptions if description)
    prepared["messages"] = prepared_messages
    prepared["_multimodal_processed"] = {
        "mode": "description" if caption_count else "placeholder",
        "provider": provider_id,
        "image_count": len(images),
        "described_image_count": caption_count,
    }
    debug_log(
        "multimodal_payload_prepared",
        provider=provider_id,
        model=request_model,
        image_count=len(images),
        described_image_count=caption_count,
    )
    return prepared
