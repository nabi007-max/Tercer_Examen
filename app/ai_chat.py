from flask import Blueprint, jsonify, request, render_template
from openai import OpenAI
from .models import Producto

chat_bp = Blueprint("chat", __name__)

# Configuración del cliente para Groq
api_key = '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'
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