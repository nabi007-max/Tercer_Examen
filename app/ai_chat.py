from flask import Blueprint, jsonify, request, render_template
from openai import OpenAI
from .models import Producto

chat_bp = Blueprint("chat", __name__)

# Configuración del cliente para Groq
api_key = 'insertar_token_de_groq'
client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

def preguntar_chatbot(preguntausuario):
    # Obtenemos productos para dar contexto (aumentamos el límite para mejor cobertura)
    productos = Producto.query.limit(20).all()
    lista_items = []
    for p in productos:
        lista_items.append(f"- {p.nombre}: ${p.precio}")
    
    lista_texto = "\n".join(lista_items)

    system_prompt = (
        f"Eres el asistente virtual de la farmacia 'Farma'. "
        f"Aquí tienes nuestra lista de productos disponibles:\n{lista_texto}\n\n"
        "Responde a las preguntas de los clientes de manera útil y breve, basándote en esta lista. "
        "Si preguntan por algo que no está en la lista, indica que no lo tenemos."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": preguntausuario}
        ]
    )
    return response.choices[0].message.content

@chat_bp.route("/chat/preguntar", methods=["POST"])
def chat_endpoint():
    data = request.get_json()
    pregunta = data.get("pregunta", "")
    
    if not pregunta:
        return jsonify({"error": "La pregunta es obligatoria"}), 400

    try:
        respuesta = preguntar_chatbot(pregunta)
        return jsonify({"respuesta": respuesta})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@chat_bp.route("/chat")
def chat_ui():
    return render_template("chatbot.html")
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
