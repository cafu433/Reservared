"""Pago con Mercado Pago (Checkout Pro).

El paciente paga en Mercado Pago y vuelve a la página de su cita. Una cita se
marca pagada sólo después de consultar el pago a la API con el Access Token del
negocio; nunca por lo que diga la URL de vuelta o el aviso por sí solos.
"""
import re

import requests
from flask import current_app

from . import ajustes, correos
from .extensions import db
from .models import Cita
from .reservas import _candado
from .disponibilidad import filtro_ocupa
from .tiempo import ahora, con_zona, fecha_larga

API = "https://api.mercadopago.com"
REFERENCIA = re.compile(r"^rr-(\d+)-([A-Za-z0-9_-]{20,64})$")


class PagoError(Exception):
    pass


class PagoRedError(PagoError):
    """Mercado Pago no respondió: vale la pena reintentar."""


def _pedir(metodo, ruta, json=None):
    try:
        r = requests.request(
            metodo,
            API + ruta,
            json=json,
            timeout=20,
            headers={"Authorization": "Bearer " + current_app.config["MP_ACCESS_TOKEN"].strip()},
        )
    except requests.RequestException:
        raise PagoRedError("No se pudo conectar con Mercado Pago. Intenta de nuevo.")
    if not 200 <= r.status_code < 300:
        try:
            detalle = r.json().get("message", r.status_code)
        except ValueError:
            detalle = r.status_code
        raise PagoError(f"Mercado Pago rechazó la solicitud ({detalle}).")
    return r.json()


def url_de_pago(cita):
    """Crea el cobro y devuelve la dirección a la que se envía al paciente."""
    if not ajustes.pagos_activos():
        raise PagoError("El pago en línea no está activado.")
    if cita.estado_pago == "pagado":
        raise PagoError("Esta hora ya está pagada.")
    if cita.estado == "cancelada" or (cita.expira and cita.expira < ahora()):
        raise PagoError("El plazo para pagar terminó y la hora se liberó. Reserva de nuevo.")

    if cita.monto <= 0:
        cita.monto = ajustes.monto_a_pagar(cita.servicio.precio)
        if cita.monto <= 0:
            raise PagoError("Este servicio no tiene precio.")
        cita.estado_pago = "pendiente"
        db.session.commit()

    volver = correos.url_absoluta("publico.cita", token=cita.token)
    preferencia = {
        "items": [{
            "id": f"cita-{cita.id}",
            "title": f"{cita.servicio.nombre} — {fecha_larga(cita.inicio)}",
            "quantity": 1,
            "unit_price": cita.monto,
            "currency_id": "CLP",
        }],
        "payer": {"name": cita.nombre, "email": cita.email},
        "external_reference": f"rr-{cita.id}-{cita.token}",
        "back_urls": {"success": volver, "pending": volver, "failure": volver},
        "auto_return": "approved",
    }
    aviso = correos.url_absoluta("publico.aviso_mercadopago")
    if aviso.startswith("https://"):
        preferencia["notification_url"] = aviso
    if cita.expira:
        preferencia["expires"] = True
        preferencia["expiration_date_to"] = con_zona(cita.expira).isoformat(timespec="milliseconds")

    r = _pedir("POST", "/checkout/preferences", preferencia)
    if not r.get("init_point"):
        raise PagoError("Mercado Pago no entregó el enlace de pago.")
    return r["init_point"]


def verificar(pago_id, cita_esperada=None):
    """Consulta un pago y, si está aprobado y corresponde, marca la cita pagada.
    Devuelve la cita (pagada o no) o None si el pago no es de una cita."""
    pago_id = str(pago_id or "")
    if not ajustes.pagos_activos() or not pago_id.isdigit():
        return None
    pago = _pedir("GET", f"/v1/payments/{pago_id}")
    if pago.get("status") != "approved":
        return None
    m = REFERENCIA.match(str(pago.get("external_reference") or ""))
    if not m:
        return None

    _candado()
    cita = Cita.query.filter_by(id=int(m.group(1)), token=m.group(2)).first()
    if not cita or (cita_esperada is not None and cita.id != cita_esperada.id):
        db.session.rollback()
        return None
    if cita.estado_pago == "pagado":
        db.session.rollback()
        return cita
    if pago.get("currency_id") != "CLP" or round(float(pago.get("transaction_amount") or 0)) < cita.monto:
        db.session.rollback()
        return None

    esperaba_pago = cita.expira is not None
    liberada = cita.estado == "cancelada"
    # Venció el plazo pero aún no se limpia: sirve sólo si nadie más tomó la hora.
    if not liberada and cita.expira and cita.expira < ahora():
        liberada = Cita.query.filter(
            Cita.id != cita.id, Cita.profesional_id == cita.profesional_id,
            Cita.inicio < cita.fin, Cita.fin > cita.inicio, filtro_ocupa(),
        ).first() is not None

    cita.estado_pago = "pagado"
    cita.pago_ref = pago_id
    cita.monto = round(float(pago["transaction_amount"]))
    cita.expira = None
    if liberada:
        cita.estado = "cancelada"
    elif cita.estado == "pendiente":
        cita.estado = "confirmada"
    db.session.commit()

    if liberada:
        correos.pago_tardio(cita)
    elif esperaba_pago:
        correos.nueva_cita(cita)
    return cita
