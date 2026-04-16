import requests
import json
import time
import uuid
from typing import Dict, Any, Optional

class ZaiMemoryTester:
    def __init__(self):
        self.base_url = "http://localhost:3001"
        self.token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImYzM2MyNDk2LWI0ZWUtNDI5Mi1iNjU2LWIwYWFlZjFkOThkMCIsImVtYWlsIjoiR3Vlc3QtMTc3NjMzMzc2ODY1MEBndWVzdC5jb20ifQ.17lbn7p3BY1pbPGX_VqFkNY6AvqgK4slP8xOEnu1p9dFQvaYhrrOBl00OrLCHAsM4VjnRnsejXnti2mQ3gSv1g"
        self.conversation = []
    
    def chat_completion(self, model: str, prompt: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        self.conversation.append({"role": "user", "content": prompt})
        
        payload = {
            "model": model,
            "messages": self.conversation,
            "stream": False
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        assistant_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self.conversation.append({"role": "assistant", "content": assistant_content})
        
        return data
    
    def test_memory(self):
        try:
            print("=== Тестирование памяти Z AI через GLM ===")
            
            # Шаг 1: Запросить запомнить число
            print("\nШаг 1: Запросить запомнить число...")
            result1 = self.chat_completion("glm-5", "Запомни число 42. Это важный тест памяти.")
            print(f"Первый ответ: {result1.get('choices', [{}])[0].get('message', {}).get('content', '')[:100]}...")
            
            # Шаг 2: Спросить что запомнил
            print("\nШаг 2: Спросить что запомнил...")
            result2 = self.chat_completion("glm-5", "Что я просил тебя запомнить?")
            
            print("\nОтвет Z AI:")
            content = result2.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(content)
            
            # Проверить ответ
            if "42" in content:
                print("\n✅ Память работает! Z AI вспомнил число 42.")
                return True
            else:
                print("\n❌ Память не работает. Z AI не вспомнил число.")
                return False
        except Exception as e:
            print(f"Error: {e}")
            return False

def main():
    tester = ZaiMemoryTester()
    success = tester.test_memory()
    
    if success:
        print("\n✅ Тест памяти пройден успешно!")
        print("Можно пушить изменения.")
    else:
        print("\n❌ Тест памяти провален. Необходимо исправить проблемы с памятью Z AI.")

if __name__ == "__main__":
    main()