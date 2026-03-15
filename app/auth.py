from decimal import Decimal
import re
from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func

from .ai_chat import generar_respuesta as generar_respuesta_ia
from .extensions import db, login_manager
from .models import DetalleVenta, Producto, User, Venta

auth_bp = Blueprint("auth", __name__)


def _get_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _generate_reset_token(email):
    serializer = _get_reset_serializer()
    return serializer.dumps(email, salt="password-reset")


def _read_reset_token(token, max_age=3600):
    serializer = _get_reset_serializer()
    return serializer.loads(token, salt="password-reset", max_age=max_age)


def _fmt_money(value):
    return f"{Decimal(value or 0):.2f}"


def _build_venta_pdf(venta):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Comprobante de Venta")

    y -= 30
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Venta ID: {venta.id}")
    y -= 18
    pdf.drawString(50, y, f"Fecha: {venta.fecha.strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 18
    pdf.drawString(50, y, f"Cliente: {venta.cliente_nombre}")
    y -= 18
    pdf.drawString(50, y, f"Vendedor: {venta.usuario.nombre if venta.usuario else '-'}")

    y -= 28
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Producto")
    pdf.drawString(300, y, "Cant.")
    pdf.drawString(360, y, "P. Unit.")
    pdf.drawString(460, y, "Subtotal")

    y -= 14
    pdf.line(50, y, 550, y)
    y -= 16

    pdf.setFont("Helvetica", 10)
    detalles = sorted(venta.detalles, key=lambda d: d.id or 0)
    for detalle in detalles:
        if y < 80:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(50, y, "Producto")
            pdf.drawString(300, y, "Cant.")
            pdf.drawString(360, y, "P. Unit.")
            pdf.drawString(460, y, "Subtotal")
            y -= 14
            pdf.line(50, y, 550, y)
            y -= 16
            pdf.setFont("Helvetica", 10)

        nombre_producto = detalle.producto.nombre if detalle.producto else "Producto"
        pdf.drawString(50, y, nombre_producto[:45])
        pdf.drawRightString(340, y, str(detalle.cantidad))
        pdf.drawRightString(430, y, _fmt_money(detalle.precio_unitario))
        pdf.drawRightString(540, y, _fmt_money(detalle.subtotal))
        y -= 16

    y -= 6
    pdf.line(360, y, 550, y)
    y -= 18
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(500, y, "TOTAL:")
    pdf.drawRightString(540, y, _fmt_money(venta.total))

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer


LOW_STOCK_THRESHOLD = 8


def _prepare_dashboard_context():
    total_productos = Producto.query.count()
    valor_stock = (
        db.session.query(func.coalesce(func.sum(Producto.precio * Producto.stock), 0)).scalar()
        or Decimal(0)
    )

    recientes_30_dias = datetime.utcnow() - timedelta(days=30)
    ventas_30_dias_rows = (
        db.session.query(
            DetalleVenta.producto_id,
            func.coalesce(func.sum(DetalleVenta.cantidad), 0).label("cantidad"),
        )
        .join(Venta, Venta.id == DetalleVenta.venta_id)
        .filter(Venta.fecha >= recientes_30_dias)
        .group_by(DetalleVenta.producto_id)
        .all()
    )
    ventas_30_dias_map = {row.producto_id: int(row.cantidad or 0) for row in ventas_30_dias_rows}
    ventas_30_dias_total = sum(ventas_30_dias_map.values())

    producto_rows = (
        db.session.query(
            Producto,
            func.coalesce(func.sum(DetalleVenta.cantidad), 0).label("ventas_totales"),
            func.coalesce(func.sum(DetalleVenta.subtotal), 0).label("ingresos_totales"),
        )
        .outerjoin(DetalleVenta, DetalleVenta.producto_id == Producto.id)
        .group_by(Producto.id)
        .order_by(Producto.nombre)
        .all()
    )

    productos_data = []
    for producto, ventas_totales, ingresos_totales in producto_rows:
        stock = producto.stock or 0
        ventas_totales = int(ventas_totales or 0)
        ingresos_totales = float(ingresos_totales or 0)
        ventas_30 = ventas_30_dias_map.get(producto.id, 0)
        promedio_diario = ventas_30 / 30 if ventas_30 > 0 else 0
        dias_estimados = round(stock / promedio_diario, 1) if promedio_diario > 0 else None

        productos_data.append(
            {
                "id": producto.id,
                "nombre": producto.nombre,
                "categoria": getattr(producto, "categoria", None) or "General",
                "stock": stock,
                "precio": float(producto.precio or 0),
                "ventas_totales": ventas_totales,
                "ingresos_totales": ingresos_totales,
                "ventas_30dias": ventas_30,
                "avg_diario": round(promedio_diario, 2),
                "dias_estimados": dias_estimados,
            }
        )

    top_products = sorted(productos_data, key=lambda p: p["ventas_totales"], reverse=True)[:3]
    low_stock_products = [p for p in productos_data if p["stock"] <= LOW_STOCK_THRESHOLD]
    stock_labels = [p["nombre"] for p in productos_data]
    stock_values = [p["stock"] for p in productos_data]

    return {
        "stock_labels": stock_labels,
        "stock_values": stock_values,
        "productos_data": productos_data,
        "top_products": top_products,
        "low_stock_products": low_stock_products,
        "total_productos": total_productos,
        "valor_stock": valor_stock,
        "valor_stock_display": f"{valor_stock:,.2f}",
        "ventas_30dias": ventas_30_dias_total,
    }


def _build_prompt(contexto):
    partes = [
        f"Total de productos registrados: {contexto['total_productos']}",
        f"Valor total del inventario: ${contexto['valor_stock_display']}",
        f"Ventas en los últimos 30 días: {contexto['ventas_30dias']}",
        "Lista de productos y desempeño:",
    ]

    for producto in contexto["productos_data"]:
        dias = f"{producto['dias_estimados']} días" if producto["dias_estimados"] else "sin proyección"
        partes.append(
            f"- {producto['nombre']} (categoría {producto['categoria']}): stock {producto['stock']}, precio "
            f"${producto['precio']:.2f}, ventas totales {producto['ventas_totales']}, ventas 30d "
            f"{producto['ventas_30dias']}, proyección {dias}."
        )

    if contexto["low_stock_products"]:
        nombres_bajos = ", ".join(p["nombre"] for p in contexto["low_stock_products"])
        partes.append(f"Productos con stock bajo: {nombres_bajos}.")
    else:
        partes.append("No se detectan productos con stock crítico en este momento.")

    if contexto["top_products"]:
        mejores = ", ".join(f"{p['nombre']} ({p['ventas_totales']} ventas)" for p in contexto["top_products"])
        partes.append(f"Top 3 de ventas: {mejores}.")

    instrucciones = (
        "Responde con tres bloques titulados ANALISIS, RESUMEN y PREDICCION. "
        "En ANALISIS describe qué muestra cada métrica, en RESUMEN destaca la categoría o producto dominante, "
        "y en PREDICCION ofrece una alerta o sugerencia para los próximos días."
    )

    ejemplo = (
        "Ejemplo:\n"
        "ANALISIS: El producto X lidera las ventas con 35 unidades y mantiene stock alto.\n"
        "RESUMEN: Moda representa el 40% del inventario activo.\n"
        "PREDICCION: Si sigue el ritmo actual, el producto Y se agotará en 3 días."
    )

    partes.append(
        "Instruction: Analiza los datos anteriores y genera una narrativa que incluya los elementos solicitados."
    )
    partes.append(ejemplo)

    prompt_body = "\n".join(partes)
    return f"{prompt_body}\n\n{instrucciones}"


def _parse_ia_response(payload):
    if not payload:
        return {"analisis": "", "resumen": "", "prediccion": ""}

    pattern = re.compile(
        r"(analisis|resumen|prediccion)\s*[:\-]\s*(.*?)(?=(analisis|resumen|prediccion)\s*[:\-]|$)",
        re.IGNORECASE | re.DOTALL,
    )

    secciones = {"analisis": "", "resumen": "", "prediccion": ""}
    for match in pattern.finditer(payload):
        nombre = match.group(1).lower()
        texto = match.group(2).strip()
        if nombre in secciones and texto:
            secciones[nombre] = texto

    if not any(secciones.values()):
        partes = [segment.strip() for segment in payload.split("\n\n") if segment.strip()]
        capitulos = list(secciones.keys())
        for idx, segmento in enumerate(partes[: len(capitulos)]):
            secciones[capitulos[idx]] = segmento

    return secciones


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)


@auth_bp.route("/")
def inicio():
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    login_error = None

    if request.method == "POST":
        nombreusuario = request.form.get("nombreusuario", "").strip()
        contrasenia = request.form.get("contrasenia", "")
        usuario = User.query.filter_by(nombre=nombreusuario).first()

        if usuario and usuario.check_password(contrasenia):
            login_user(usuario)
            return redirect("/admin")

        login_error = "Usuario o contraseña incorrectos."

    return render_template("login.html", login_error=login_error)


@auth_bp.route("/registro", methods=["POST"])
def registro():
    nombre = request.form.get("nuevo_nombre", "").strip()
    email = request.form.get("nuevo_email", "").strip()
    password = request.form.get("nuevo_password", "")
    password_confirm = request.form.get("nuevo_password_confirm", "")

    if not nombre or not email or not password or not password_confirm:
        return render_template("login.html", registro_error="Todos los campos son obligatorios.")

    if password != password_confirm:
        return render_template("login.html", registro_error="Las contrasenas no coinciden.")

    if User.query.filter_by(nombre=nombre).first():
        return render_template("login.html", registro_error="El nombre de usuario ya existe.")

    if User.query.filter_by(email=email).first():
        return render_template("login.html", registro_error="El correo ya esta registrado.")

    usuario = User(nombre=nombre, email=email, rol="vendedor")
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.commit()

    return render_template("login.html", registro_ok="Cuenta creada correctamente. Ya puedes iniciar sesion.")


@auth_bp.route("/recuperar", methods=["GET", "POST"])
def recuperar_password():
    reset_link = None
    mensaje = None

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        usuario = User.query.filter_by(email=email).first()

        if usuario:
            token = _generate_reset_token(usuario.email)
            reset_link = url_for("auth.restablecer_password", token=token, _external=True)
            mensaje = "Se genero un enlace de recuperacion."
        else:
            mensaje = "No existe un usuario con ese correo."

    return render_template("forgot_password.html", reset_link=reset_link, mensaje=mensaje)


@auth_bp.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer_password(token):
    error = None

    try:
        email = _read_reset_token(token)
    except SignatureExpired:
        return render_template("reset_password.html", token_valido=False, error="El enlace expiro.")
    except BadSignature:
        return render_template("reset_password.html", token_valido=False, error="El enlace no es valido.")

    usuario = User.query.filter_by(email=email).first()
    if not usuario:
        return render_template("reset_password.html", token_valido=False, error="Usuario no encontrado.")

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not password:
            error = "La contrasena es obligatoria."
        elif password != password_confirm:
            error = "Las contrasenas no coinciden."
        else:
            usuario.set_password(password)
            db.session.commit()
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token_valido=True, error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/dashboard")
@login_required
def dashboard():
    contexto = _prepare_dashboard_context()
    return render_template(
        "dashboard.html",
        total_productos=contexto["total_productos"],
        valor_stock=contexto["valor_stock_display"],
        nombres=contexto["stock_labels"],
        stock=contexto["stock_values"],
        top_products=contexto["top_products"],
        low_stock_products=contexto["low_stock_products"],
        ventas_30dias=contexto["ventas_30dias"],
        last_update=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


@auth_bp.route("/analisis-ia")
@login_required
def analisis_ia():
    contexto = _prepare_dashboard_context()
    prompt = _build_prompt(contexto)
    respuesta = generar_respuesta_ia(prompt)

    if not respuesta:
        fallback = {
            "analisis": "No se pudo generar el análisis automático (falta GROQ_API_KEY).",
            "resumen": "Activa la clave GROQ_API_KEY para habilitar la IA.",
            "prediccion": "La predicción no está disponible sin credenciales.",
        }
        return jsonify(fallback)

    secciones = _parse_ia_response(respuesta)
    defaults = {
        "analisis": secciones.get("analisis")
        or "IA generó una respuesta, pero no se detectó la sección ANALISIS.",
        "resumen": secciones.get("resumen")
        or "IA generó una respuesta, pero no se detectó la sección RESUMEN.",
        "prediccion": secciones.get("prediccion")
        or "IA generó una respuesta, pero no se detectó la sección PREDICCION.",
    }
    return jsonify(defaults)


@auth_bp.route("/ventas/<int:venta_id>/pdf")
@login_required
def venta_pdf(venta_id):
    venta = Venta.query.get_or_404(venta_id)
    try:
        pdf_buffer = _build_venta_pdf(venta)
    except ImportError:
        abort(500, description="Falta instalar reportlab para generar PDF.")

    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"comprobante_venta_{venta.id}.pdf",
    )
