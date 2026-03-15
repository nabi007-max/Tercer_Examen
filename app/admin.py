from datetime import datetime

from flask import flash, redirect, url_for
from flask_admin import AdminIndexView
from flask_admin.actions import action
from flask_admin.contrib.sqla import ModelView
from flask_admin.menu import MenuLink
from flask_login import current_user
from markupsafe import Markup

from .extensions import admin, db
from .models import DetalleVenta, Producto, User, Venta


AdminIndexView.extra_css = ["/static/admin_horizontal_static.css"]


class SecurityModelView(ModelView):
    extra_css = ["/static/admin_horizontal_static.css"]
    disallow_for_vendedor = False

    def is_accessible(self):
        if not current_user.is_authenticated:
            return False

        # El perfil "vendedor" solo puede acceder a Venta y DetalleVenta.
        if self.disallow_for_vendedor and getattr(current_user, "rol", None) == "vendedor":
            return False

        return True

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("auth.login"))


class UserAdminView(SecurityModelView):
    column_exclude_list = ["password"]
    disallow_for_vendedor = True


class ProductoAdminView(SecurityModelView):
    disallow_for_vendedor = True
    column_exclude_list = ["detalles_venta"]
    form_excluded_columns = ["detalles_venta"]
    column_details_exclude_list = ["detalles_venta"]


class VentaAdminView(SecurityModelView):
    column_list = ["id", "fecha", "cliente_nombre", "usuario", "estado", "total", "comprobante"]
    form_columns = ["fecha", "cliente_nombre", "usuario"]
    column_labels = {"comprobante": "Comprobante"}
    can_view_details = True

    def _usuario_autenticado(self):
        if not current_user.is_authenticated:
            return []
        return User.query.filter_by(id_usuario=current_user.id).all()

    def create_form(self, obj=None):
        form = super().create_form(obj)
        form.usuario.query_factory = self._usuario_autenticado
        form.usuario.data = User.query.get(current_user.id)
        return form

    def edit_form(self, obj=None):
        form = super().edit_form(obj)
        form.usuario.query_factory = self._usuario_autenticado
        form.usuario.data = User.query.get(current_user.id)
        return form

    @action("confirmar", "Confirmar ventas", "Confirmar ventas seleccionadas?")
    def action_confirmar(self, ids):
        ventas = self.session.query(Venta).filter(Venta.id.in_(ids)).all()
        confirmadas = 0
        omitidas = 0

        try:
            for venta in ventas:

                if venta.estado in ("confirmada", "anulada"):
                    omitidas += 1
                    continue

                if not venta.detalles:
                    omitidas += 1
                    continue

                for detalle in venta.detalles:
                    producto = detalle.producto

                    if producto is None:
                        raise ValueError(f"Detalle sin producto en venta #{venta.id}")

                    if producto.stock < detalle.cantidad:
                        raise ValueError(
                            f"Stock insuficiente para '{producto.nombre}' en venta #{venta.id}"
                        )

                for detalle in venta.detalles:
                    detalle.producto.stock -= detalle.cantidad

                venta.estado = "confirmada"
                venta.fecha_confirmacion = datetime.utcnow()
                confirmadas += 1

            self.session.commit()
            flash(f"Ventas confirmadas: {confirmadas} | Omitidas: {omitidas}", "success")

        except Exception as ex:
            self.session.rollback()
            flash(str(ex), "error")

    @action("anular", "Anular ventas", "Anular ventas seleccionadas?")
    def action_anular(self, ids):

        ventas = self.session.query(Venta).filter(Venta.id.in_(ids)).all()

        anuladas = 0
        omitidas = 0

        try:
            for venta in ventas:

                if venta.estado != "confirmada":
                    omitidas += 1
                    continue

                for detalle in venta.detalles:
                    detalle.producto.stock += detalle.cantidad

                venta.estado = "anulada"
                anuladas += 1

            self.session.commit()

            flash(f"Ventas anuladas: {anuladas} | Omitidas: {omitidas}", "success")

        except Exception as ex:
            self.session.rollback()
            flash(str(ex), "error")

    def on_model_change(self, form, model, is_created):
        model.usuario = User.query.get(current_user.id)

        if not is_created and model.estado != "borrador":
            raise ValueError("Solo se puede editar una venta en estado borrador")

        return super().on_model_change(form, model, is_created)

    def delete_model(self, model):

        if model.estado != "borrador":
            raise ValueError("Solo se puede eliminar una venta en estado borrador")

        return super().delete_model(model)

    def _comprobante_formatter(self, context, model, name):

        href = url_for("auth.venta_pdf", venta_id=model.id)

        return Markup(f'<a href="{href}" target="_blank">Descargar PDF</a>')

    column_formatters = {
        "comprobante": _comprobante_formatter
    }


class DetalleVentaAdminView(SecurityModelView):

    column_list = ["id", "venta", "producto", "cantidad", "precio_unitario", "subtotal"]

    form_columns = ["venta", "producto", "cantidad"]

    def on_model_change(self, form, model, is_created):

        if model.venta and model.venta.estado != "borrador":
            raise ValueError("Solo puedes modificar detalles de una venta en borrador")

        return super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):

        if model.venta and model.venta.estado != "borrador":
            raise ValueError("Solo puedes eliminar detalles de una venta en borrador")

        return super().on_model_delete(model)


def configuracion_admin():

    admin.add_view(UserAdminView(User, db.session))
    admin.add_view(ProductoAdminView(Producto, db.session))
    admin.add_view(VentaAdminView(Venta, db.session))
    admin.add_view(DetalleVentaAdminView(DetalleVenta, db.session))
    admin.add_link(MenuLink(name="Chatbot", url="/chat"))

    admin.add_link(MenuLink(name="Dashboard IA", url="/dashboard"))
    admin.add_link(MenuLink(name="Cerrar sesión", url="/logout"))
