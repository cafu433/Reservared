"""Ajustes que el negocio cambia desde el panel. Las claves secretas
(Mercado Pago, Google, correo) van en variables de entorno, no aquí."""
import json

from flask import current_app

from .extensions import db
from .models import Ajuste

PREDETERMINADOS = {
    "anticipacion_horas": 2,
    "dias_maximo": 60,
    "intervalo": 0,  # 0 = cada hora parte al terminar la anterior
    "estado_inicial": "confirmada",
    "horas_cancelar": 24,
    "pedir_rut": True,
    "email_aviso": "",
    "mensaje_confirmacion": "Te esperamos. Si no puedes venir, cancela tu hora desde el enlace del correo.",
    "color": "#2f7a6b",
    "pago_modo": "ninguno",  # ninguno | opcional | obligatorio
    "pasarelas": ["webpay"],  # webpay y/o mercadopago
    "pago_porcentaje": 100,
    "pago_minutos": 20,
    "google_invitar": True,  # Google manda la invitación de calendario al paciente
    # Lo escribe la conexión con Google, no el formulario.
    "google_refresh_token": "",
    "google_cuenta": "",
}


def todos():
    datos = dict(PREDETERMINADOS)
    for fila in Ajuste.query.all():
        datos[fila.clave] = fila.dato
    return datos


def get(clave):
    fila = db.session.get(Ajuste, clave)
    return fila.dato if fila else PREDETERMINADOS.get(clave)


def guardar(cambios):
    for clave, valor in cambios.items():
        fila = db.session.get(Ajuste, clave)
        if fila is None:
            fila = Ajuste(clave=clave)
            db.session.add(fila)
        fila.valor = json.dumps(valor)
    db.session.commit()


def pasarelas():
    """Medios de pago en línea habilitados y configurados."""
    listas = []
    for p in get("pasarelas") or []:
        if p == "webpay":
            from . import webpay

            if webpay.disponible():
                listas.append(p)
        elif p == "mercadopago" and current_app.config["MP_ACCESS_TOKEN"]:
            listas.append(p)
    return listas


def pagos_activos():
    return get("pago_modo") != "ninguno" and bool(pasarelas())


def pago_obligatorio():
    return pagos_activos() and get("pago_modo") == "obligatorio"


def monto_a_pagar(precio):
    pct = min(100, max(1, int(get("pago_porcentaje") or 100)))
    return round(int(precio or 0) * pct / 100)
