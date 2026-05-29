#!/usr/bin/env python3
"""Generate an OpenAI Codex model catalog for this proxy."""

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PY_DIR = ROOT_DIR / "py"
PYDEPS_DIR = ROOT_DIR / "pydeps"
if PYDEPS_DIR.is_dir() and str(PYDEPS_DIR) not in sys.path:
    sys.path.insert(0, str(PYDEPS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))


BASE_INSTRUCTIONS = """You are Codex, a coding agent. The user and you share one workspace.

Work like a pragmatic senior software engineer: inspect the repository before changing it, keep edits scoped, use tools to read and modify files, and verify the result with targeted commands when possible.

You are usually running on Windows. Use Windows paths and PowerShell/CMD commands such as Get-ChildItem, Get-Content, rg, git status --short, git diff, and project test commands. Do not assume Linux shell syntax unless the environment explicitly says so.

When tool calling is available, request tools for filesystem inspection, command execution, and code edits instead of pretending those actions were done. Use the exact listed tool names and schemas; do not invent tools named shell, bash, or shell_command unless they are listed. If a tool-name error says "Tool X does not exist", retry with an exact available tool name instead of claiming that tools are unavailable, tool limits are exhausted, or the user must run commands manually. If a provider uses the proxy prompt-tool shim, still follow the tool schema exactly so the proxy can translate your request back into OpenAI-compatible tool calls.

For repository work, use a Codex-style loop: inspect files, make focused edits, run targeted validation, and then summarize the result. Read relevant files before editing: use rg/search to locate code, then inspect the exact function, class, or surrounding lines before deciding on a change. Do not rewrite entire files unless the user explicitly asks or the file is tiny and a full rewrite is clearly simpler; prefer a focused patch to the smallest section that solves the task. For large files, read focused ranges or chunks instead of dumping the whole file. Treat requirements as a checklist and verify edge cases before claiming success, especially persistence, deletion, missing IDs/files, repeated operations, and boundary cases named by the user. Do not mark a requirement satisfied from a weak inference: for example, max(existing_id)+1 does not prove IDs are never reused after deletion; add or run an explicit test for the edge case. Keep user-visible progress explicit with concise statuses or plan updates that name what you inspected, changed, or validated; do not expose hidden chain-of-thought. For implementation tasks, talk to the user only after the work is complete and verified, or to report a real blocker with concrete evidence. If an edit tool such as apply_patch is available, use it for manual file edits; if it is a freeform tool, send raw patch text beginning with *** Begin Patch and ending with *** End Patch, not JSON. If apply_patch fails with an incompatible payload error, do not repeat the same malformed call; retry once with raw patch text or use another listed edit method. If a tool call fails, read the tool error and retry with corrected arguments or a real available tool name.
""".strip()

REASONING_LEVELS = [
    {"effort": "low", "description": "Fast responses with lighter reasoning"},
    {"effort": "medium", "description": "Balanced reasoning for everyday coding"},
    {"effort": "high", "description": "Deeper reasoning for complex tasks"},
    {"effort": "xhigh", "description": "Extra reasoning depth when the client requests it"},
]

PROVIDER_DISPLAY_NAMES = {
    "arcee": "Arcee",
    "deepseek": "DeepSeek",
    "gemini-web": "Gemini Web",
    "google-ai-studio": "Google AI Studio",
    "google-ai-studio-web": "Google AI Studio Web",
    "grok": "Grok",
    "inception": "Inception",
    "inflection": "Inflection",
    "kimi": "Kimi",
    "longcat": "LongCat",
    "mimo": "Mimo",
    "mistral": "Mistral",
    "openai-web": "OpenAI Web",
    "perplexity": "Perplexity",
    "phind": "Phind",
    "pi-local": "Pi Local",
    "qwen-ai": "Qwen",
    "uncloseai": "UncloseAI",
    "zai": "Z.ai",
}

PROVIDER_CONTEXT_WINDOWS = {
    "gemini-web": 1_048_576,
    "google-ai-studio": 1_048_576,
    "google-ai-studio-web": 1_048_576,
    "kimi": 200_000,
    "mistral": 128_000,
    "openai-web": 128_000,
    "qwen-ai": 128_000,
    "zai": 128_000,
}

MODEL_CONTEXT_HINTS = (
    ("gemini", 1_048_576),
    ("ai-studio", 1_048_576),
    ("kimi", 200_000),
    ("codestral", 256_000),
    ("devstral", 128_000),
    ("mistral", 128_000),
    ("glm", 128_000),
    ("qwen", 128_000),
)

PREFERRED_MODEL_PRIORITY = {
    "mistral-small-2603": 0,
    "devstral-2512": 1,
    "codestral-2508": 2,
    "glm-5-agent": 3,
    "glm-5.1-agent": 4,
    "google-ai-studio": 5,
    "uncloseai-hermes": 6,
}

STATIC_PROVIDERS = [
    {
        "provider": "zai",
        "owned_by": "z.ai",
        "module": "zai_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["ZAI_TOKEN"],
    },
    {
        "provider": "deepseek",
        "owned_by": "DeepSeek",
        "module": "deepseek_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["DEEPSEEK_TOKEN"],
    },
    {
        "provider": "arcee",
        "owned_by": "Arcee",
        "module": "arcee_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["ARCEE_ACCESS_TOKEN"],
    },
    {
        "provider": "google-ai-studio",
        "owned_by": "Google AI Studio / Gemini API",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.1-pro-preview-customtools",
            "gemini-3.1-flash-lite",
            "gemini-3-pro-preview",
            "gemini-3-pro-image-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ],
        "requires_env": ["GOOGLE_AI_STUDIO_API_KEY"],
    },
    {
        "provider": "google-ai-studio-web",
        "owned_by": "aistudio.google.com",
        "models": [
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.1-pro-preview-customtools",
            "gemini-3.1-flash-lite",
            "gemini-3-pro-preview",
            "gemini-3-pro-image-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ],
        "requires_env": ["GOOGLE_AI_STUDIO_WEB_COOKIE"],
    },
    {
        "provider": "gemini-web",
        "owned_by": "gemini.google.com",
        "models": [
            "gemini-3-flash",
            "gemini-3-pro",
            "gemini-3-flash-thinking",
        ],
        "requires_env": ["GEMINI_WEB_SECURE_1PSID"],
    },
    {
        "provider": "grok",
        "owned_by": "grok.com",
        "module": "grok_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["GROK_COOKIE"],
    },
    {
        "provider": "kimi",
        "owned_by": "Kimi",
        "module": "kimi_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["KIMI_TOKEN"],
    },
    {
        "provider": "inception",
        "owned_by": "Inception Labs",
        "module": "inception_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["INCEPTION_SESSION_TOKEN"],
    },
    {
        "provider": "longcat",
        "owned_by": "longcat.chat",
        "module": "longcat_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["LONGCAT_COOKIE"],
    },
    {
        "provider": "mistral",
        "owned_by": "console.mistral.ai",
        "module": "mistral_proxy.py",
        "models": "DEFAULT_SUPPORTED_MODELS",
        "requires_env": ["MISTRAL_COOKIE"],
    },
    {
        "provider": "mimo",
        "owned_by": "Mimo",
        "module": "mimo_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN"],
    },
    {
        "provider": "openai-web",
        "owned_by": "chatgpt.com",
        "models": ["chatgpt-auto"],
        "requires_env": ["OPENAI_WEB_ACCESS_TOKEN"],
    },
    {
        "provider": "perplexity",
        "owned_by": "perplexity.ai",
        "module": "perplexity_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["PERPLEXITY_COOKIE"],
    },
    {
        "provider": "phind",
        "owned_by": "phindai.org",
        "module": "phind_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["PHIND_COOKIE"],
    },
    {
        "provider": "inflection",
        "owned_by": "Inflection AI (api.inflection.ai)",
        "models": ["pi-api", "pi-3.1"],
        "requires_env": ["INFLECTION_API_KEY", "PI_INFLECTION_API_KEY"],
    },
    {
        "provider": "pi-local",
        "owned_by": "pi.ai",
        "module": "pi_local_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": [],
    },
    {
        "provider": "qwen-ai",
        "owned_by": "chat.qwen.ai",
        "module": "qwen_ai_proxy.py",
        "models": "SUPPORTED_MODELS",
        "requires_env": ["QWEN_AI_COOKIE"],
    },
    {
        "provider": "uncloseai",
        "owned_by": "uncloseai.com",
        "module": "uncloseai_proxy.py",
        "models": "MODEL_TARGETS",
        "requires_env": [],
    },
]

NATIVE_TOOL_PROVIDERS = {"inflection", "uncloseai", "google-ai-studio"}
NATIVE_IMAGE_PROVIDERS = {"google-ai-studio"}
NATIVE_IMAGE_MODELS = {"uncloseai-qwen-vl"}
MODEL_ALIASES = {
    "gemini-web": "gemini-3-flash",
    "gemini-web-fast": "gemini-3-flash",
    "gemini-web-pro": "gemini-3-pro",
    "gemini-web-thinking": "gemini-3-flash-thinking",
    "google-ai-studio": "gemini-2.5-flash",
    "ai-studio": "gemini-2.5-flash",
    "ai-studio-pro": "gemini-2.5-pro",
    "ai-studio-flash": "gemini-2.5-flash",
    "ai-studio-lite": "gemini-2.5-flash-lite",
    "ai-studio-3.5-flash": "gemini-3.5-flash",
    "ai-studio-3.1-pro": "gemini-3.1-pro-preview",
    "ai-studio-3.1-pro-customtools": "gemini-3.1-pro-preview-customtools",
    "ai-studio-3.1-flash-lite": "gemini-3.1-flash-lite",
    "chatgpt": "chatgpt-auto",
    "openai-web": "chatgpt-auto",
    "inflection-pi": "pi-api",
    "inflection_3_pi": "pi-api",
    "pi-3-1": "pi-3.1",
    "qwen": "Qwen3.7-Max",
    "qwen3": "Qwen3.7-Max",
    "qwen3.7": "Qwen3.7-Max",
    "qwen3.7-max": "Qwen3.7-Max",
    "qwen3.7-max-preview": "Qwen3.7-Max",
}


def _display_provider(provider_id: str) -> str:
    return PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id.replace("-", " ").title())


def _display_model(model_id: str) -> str:
    words = re.split(r"[-_]+", str(model_id or "").strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word)


def _context_window(spec: dict, default_context_window: int) -> int:
    provider_id = str(spec.get("provider") or "").strip().lower()
    model_id = str(spec.get("id") or "").strip().lower()
    for needle, size in MODEL_CONTEXT_HINTS:
        if needle in model_id:
            return size
    return PROVIDER_CONTEXT_WINDOWS.get(provider_id, default_context_window)


def _priority(spec: dict, index: int) -> int:
    model_id = str(spec.get("id") or "")
    if model_id in PREFERRED_MODEL_PRIORITY:
        return PREFERRED_MODEL_PRIORITY[model_id]
    return 100 + index


def _static_literal(module_name: str, variable: str):
    module_path = PY_DIR / module_name
    if not module_path.is_file():
        return None
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == variable for target in node.targets):
            continue
        try:
            return ast.literal_eval(node.value)
        except Exception:
            return None
    return None


def _models_from_static_provider(provider: dict) -> list[str]:
    source = provider.get("models")
    if isinstance(source, list):
        return [str(item) for item in source if str(item or "").strip()]
    if not isinstance(source, str):
        return []
    value = _static_literal(str(provider.get("module") or ""), source)
    if isinstance(value, dict):
        return [str(key) for key in value.keys() if str(key or "").strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _capabilities(provider_id: str, model_id: str) -> dict:
    native_tools = provider_id in NATIVE_TOOL_PROVIDERS
    tools = True
    native_images = provider_id in NATIVE_IMAGE_PROVIDERS or model_id in NATIVE_IMAGE_MODELS
    images = True
    return {
        "chat_completions": True,
        "responses": True,
        "tools": tools,
        "native_tools": native_tools,
        "prompt_tool_shim": tools and not native_tools,
        "streaming": True,
        "images": images,
        "native_images": native_images,
        "image_descriptions": images and not native_images,
    }


def _static_model_specs() -> list[dict]:
    specs = []
    seen = set()
    for provider in STATIC_PROVIDERS:
        provider_id = str(provider["provider"])
        owned_by = str(provider.get("owned_by") or provider_id)
        requires_env = list(provider.get("requires_env") or [])
        for model_id in _models_from_static_provider(provider):
            key = (provider_id.lower(), model_id.lower())
            if key in seen:
                continue
            seen.add(key)
            specs.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": owned_by,
                    "provider": provider_id,
                    "requires_env": requires_env,
                    "capabilities": _capabilities(provider_id, model_id),
                }
            )
    return specs


def load_model_specs(force_static: bool = False) -> list[dict]:
    if force_static:
        return _static_model_specs()

    try:
        from py.provider_registry import MODEL_SPECS

        return list(MODEL_SPECS)
    except Exception:
        try:
            from provider_registry import MODEL_SPECS

            return list(MODEL_SPECS)
        except Exception:
            return _static_model_specs()


def _codex_model(spec: dict, index: int, default_context_window: int) -> dict:
    model_id = str(spec.get("id") or "").strip()
    provider_id = str(spec.get("provider") or "").strip()
    capabilities = spec.get("capabilities") if isinstance(spec.get("capabilities"), dict) else {}
    context_window = _context_window(spec, default_context_window)
    provider_name = _display_provider(provider_id)
    native_tools = bool(capabilities.get("native_tools"))
    prompt_tool_shim = bool(capabilities.get("prompt_tool_shim"))
    tools = bool(capabilities.get("tools"))
    native_images = bool(capabilities.get("native_images"))
    images = bool(capabilities.get("images"))

    tool_mode = "native tools" if native_tools else "prompt tool shim" if prompt_tool_shim else "no tools"
    image_mode = "native images" if native_images else "proxy image descriptions" if images else "text only"

    return {
        "slug": model_id,
        "display_name": f"{_display_model(model_id)} ({provider_name})",
        "description": f"{model_id} routed through risu-zai-proxy provider {provider_id}; {tool_mode}; {image_mode}.",
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": REASONING_LEVELS,
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": _priority(spec, index),
        "additional_speed_tiers": [],
        "service_tiers": [],
        "availability_nux": None,
        "upgrade": None,
        "base_instructions": BASE_INSTRUCTIONS,
        "model_messages": {
            "instructions_template": "{{ personality }}\n\n" + BASE_INSTRUCTIONS,
            "instructions_variables": {
                "personality_default": "",
                "personality_friendly": "",
                "personality_pragmatic": "",
            },
        },
        "supports_reasoning_summaries": False,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "default_verbosity": "low",
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image",
        "truncation_policy": {"mode": "tokens", "limit": 10_000},
        "supports_parallel_tool_calls": tools,
        "supports_image_detail_original": native_images,
        "context_window": context_window,
        "max_context_window": context_window,
        "effective_context_window_percent": 90,
        "experimental_supported_tools": [],
        "input_modalities": ["text", "image"] if images else ["text"],
        "supports_search_tool": False,
    }


def _selected_specs(args) -> list[dict]:
    providers = {item.strip().lower() for item in args.provider or [] if item.strip()}
    models = set()
    for item in args.model or []:
        text = item.strip()
        if not text:
            continue
        models.add(text.lower())
        alias_target = MODEL_ALIASES.get(text.lower())
        if alias_target:
            models.add(alias_target.lower())
    selected = []
    for spec in load_model_specs(args.static):
        provider_id = str(spec.get("provider") or "").strip().lower()
        model_id = str(spec.get("id") or "").strip().lower()
        if providers and provider_id not in providers:
            continue
        if models and model_id not in models:
            continue
        selected.append(spec)
    return selected


def build_catalog(args) -> dict:
    specs = _selected_specs(args)
    models = [
        _codex_model(spec, index, args.default_context_window)
        for index, spec in enumerate(specs)
    ]
    models.sort(key=lambda item: (item["priority"], item["display_name"].lower()))
    return {"models": models}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a model_catalog_json file for OpenAI Codex."
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write catalog JSON to this path. Defaults to stdout.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        help="Include only this provider id. Can be repeated.",
    )
    parser.add_argument(
        "--model",
        action="append",
        help="Include only this model id. Can be repeated.",
    )
    parser.add_argument(
        "--default-context-window",
        type=int,
        default=128_000,
        help="Fallback context window for models without provider hints.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 for compact output.",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Read model ids from source files instead of importing provider modules.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    catalog = build_catalog(args)
    if not catalog["models"]:
        raise SystemExit("No models matched the requested filters")

    indent = None if args.indent == 0 else args.indent
    text = json.dumps(catalog, ensure_ascii=False, indent=indent)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
