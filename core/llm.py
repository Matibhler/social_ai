"""
Cliente LLM local vía Ollama.
Proporciona generate() y chat() como funciones simples.
"""

import json
from typing import Generator

import httpx

from core.config import settings
from core.logger import get_logger

log = get_logger(__name__)


class OllamaClient:
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL

    def generate(self, prompt: str, system: str = "", stream: bool = False) -> str:
        """Genera texto a partir de un prompt."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 2048},
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except httpx.HTTPError as e:
            log.error("Error llamando a Ollama: %s", e)
            raise

    def chat(self, messages: list[dict], system: str = "") -> str:
        """Chat multi-turno."""
        payload = {
            "model": self.model,
            "messages": messages,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 2048},
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except httpx.HTTPError as e:
            log.error("Error en chat con Ollama: %s", e)
            raise

    def json_generate(self, prompt: str, system: str = "") -> dict:
        """Genera y parsea JSON directamente."""
        full_system = (
            system + "\nResponde ÚNICAMENTE con JSON válido, sin texto adicional."
        )
        text = self.generate(prompt, system=full_system)
        # Extraer bloque JSON si viene envuelto en ```json
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return json.loads(self._repair_json(text))

    @staticmethod
    def _repair_json(text: str) -> str:
        """Closes unclosed brackets/strings in a truncated JSON response."""
        stack = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch in "{[":
                    stack.append("}" if ch == "{" else "]")
                elif ch in "}]" and stack and stack[-1] == ch:
                    stack.pop()
        if in_string:
            text += '"'
        text += "".join(reversed(stack))
        return text

    def health_check(self) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False


llm = OllamaClient()
