import sys
import uuid
from typing import Any, Dict

import requests


class ZaiSessionTester:
    def __init__(self):
        self.base_url = "https://risu-zai-proxy-archive.vercel.app"
        self.token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImYzM2MyNDk2LWI0ZWUtNDI5Mi1iNjU2LWIwYWFlZjFkOThkMCIsImVtYWlsIjoiR3Vlc3QtMTc3NjMzMzc2ODY1MEBndWVzdC5jb20ifQ.17lbn7p3BY1pbPGX_VqFkNY6AvqgK4slP8xOEnu1p9dFQvaYhrrOBl00OrLCHAsM4VjnRnsejXnti2mQ3gSv1g"

    def chat_completion(self, prompt: str, conversation_id: str = "") -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "glm-5",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()

    def test_memory(self) -> bool:
        secret = "code-" + uuid.uuid4().hex[:8]

        print("Session A: store a secret")
        first = self.chat_completion(f"Please remember this code for this session only: {secret}.")
        first_text = first.get("choices", [{}])[0].get("message", {}).get("content", "")
        conversation_id = first.get("conversation_id", "")
        if not conversation_id:
            print("\nFAIL: response did not include conversation_id.")
            return False
        print(first_text)

        print("\nSession A: ask for the secret again")
        second = self.chat_completion("What code did I ask you to remember? Answer only the code.", conversation_id=conversation_id)
        second_text = second.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(second_text)

        print("\nSession B: ask without prior context")
        third = self.chat_completion("What code did I ask you to remember? Answer only the code.")
        third_text = third.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(third_text)

        if secret not in second_text:
            print("\nFAIL: session A did not remember the secret.")
            return False

        if secret in third_text:
            print("\nFAIL: session B leaked session A memory.")
            return False

        print("\nPASS: session memory works and sessions are isolated.")
        return True


def main():
    tester = ZaiSessionTester()
    success = tester.test_memory()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
