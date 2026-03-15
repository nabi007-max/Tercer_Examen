import os
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None
else:
    _original_httpx_init = httpx.Client.__init__

    def _patched_httpx_init(self, *args, **kwargs):
        kwargs = dict(kwargs)
        kwargs.pop("proxies", None)
        return _original_httpx_init(self, *args, **kwargs)

    httpx.Client.__init__ = _patched_httpx_init


try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - guard in environments without OpenAI
    OpenAI = None


_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if _client:
        return _client

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or OpenAI is None:
        return None

    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def generar_respuesta(prompt: str, temperature: float = 0.35) -> Optional[str]:
    client = _get_client()
    if not client:
        return None

    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        temperature=temperature,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un analista de datos comerciales que convierte "
                    "información financiera en lenguaje claro, estructurado y "
                    "con recomendaciones accionables."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    choices = getattr(response, "choices", None)
    if not choices:
        return None

    return choices[0].message.content
