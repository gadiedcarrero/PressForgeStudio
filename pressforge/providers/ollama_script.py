"""ScriptProvider local con Ollama (gratis, sin coste de API).

Reutiliza TODA la lógica y los prompts de OpenAIScriptProvider, pero apuntando
al endpoint compatible con OpenAI que expone Ollama (http://localhost:11434/v1).
Solo cambia el "motor". Se activa con SCRIPT_PROVIDER=ollama en .env.

Recomendado: un modelo multilingüe con buena salida estructurada, p. ej.
`qwen3:30b`. Los modelos de razonamiento (deepseek-r1) NO van bien aquí: su
"pensamiento" rompe el JSON estructurado.
"""
from __future__ import annotations

from openai import OpenAI

from ..config import get_settings
from .openai_script import OpenAIScriptProvider


class OllamaScriptProvider(OpenAIScriptProvider):
    def __init__(self) -> None:
        s = get_settings()
        super().__init__(
            client_obj=OpenAI(base_url=s.ollama_base_url, api_key="ollama"),
            model=s.ollama_model,
        )
