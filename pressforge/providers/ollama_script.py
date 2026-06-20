"""ScriptProvider local con Ollama (gratis, sin coste de API).

Reutiliza TODA la lógica y los prompts de OpenAIScriptProvider, pero apuntando
al endpoint compatible con OpenAI que expone Ollama (http://localhost:11434/v1).
Solo cambia el "motor". Se activa con SCRIPT_PROVIDER=ollama en .env.

Recomendado: un modelo multilingüe con buena salida estructurada, p. ej.
`qwen3:30b`. Se DESACTIVA su "pensamiento" (enable_thinking=False): el guion
sale en ~30 s en vez de ~3 min, y el JSON estructurado queda igual de válido.
"""
from __future__ import annotations

from types import SimpleNamespace

from openai import OpenAI

from ..config import get_settings
from .openai_script import OpenAIScriptProvider


def _no_think_client(client: OpenAI) -> SimpleNamespace:
    """Envuelve el cliente para que cada `parse` desactive el pensamiento de
    qwen3 (chat_template_kwargs.enable_thinking=False) → mucho más rápido."""
    real_parse = client.beta.chat.completions.parse

    def parse(*args, **kwargs):
        eb = dict(kwargs.pop("extra_body", {}) or {})
        eb.setdefault("chat_template_kwargs", {"enable_thinking": False})
        return real_parse(*args, extra_body=eb, **kwargs)

    completions = SimpleNamespace(parse=parse)
    return SimpleNamespace(beta=SimpleNamespace(chat=SimpleNamespace(completions=completions)))


class OllamaScriptProvider(OpenAIScriptProvider):
    def __init__(self) -> None:
        s = get_settings()
        super().__init__(
            client_obj=OpenAI(base_url=s.ollama_base_url, api_key="ollama"),
            model=s.ollama_model,
        )
        # Desactiva el pensamiento del modelo en todas las llamadas (rápido).
        self._client = _no_think_client(self._client)
