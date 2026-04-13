import time


def openai_chunk(response_id: str, model: str, created: int, delta: dict, finish_reason=None):
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


class OpenAIStreamBuilder:
    def __init__(self, response_id: str, model: str):
        self.response_id = response_id
        self.model = model
        self.created = int(time.time())
        self.role_sent = False

    def set_response_id(self, response_id: str):
        if response_id:
            self.response_id = response_id

    def ensure_role(self, mode: str = "content"):
        if self.role_sent:
            return None
        self.role_sent = True
        if mode == "reasoning":
            return openai_chunk(self.response_id, self.model, self.created, {"role": "assistant", "reasoning_content": ""})
        return openai_chunk(self.response_id, self.model, self.created, {"role": "assistant", "content": ""})

    def content(self, text: str):
        text = str(text or "")
        if not text:
            return
        role_chunk = self.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
        yield openai_chunk(self.response_id, self.model, self.created, {"content": text})

    def reasoning(self, text: str):
        text = str(text or "")
        if not text:
            return
        role_chunk = self.ensure_role("reasoning")
        if role_chunk is not None:
            yield role_chunk
        yield openai_chunk(self.response_id, self.model, self.created, {"reasoning_content": text})

    def finish(self, finish_reason: str = "stop"):
        return openai_chunk(self.response_id, self.model, self.created, {}, finish_reason=finish_reason)
