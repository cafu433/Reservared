"""Pago con Mercado Pago (Checkout Pro).

El paciente paga en Mercado Pago y vuelve a la página de su cita. Una cita se
marca pagada sólo después de consultar el pago a la API con el Access Token del
negocio; nunca por lo que diga la URL de vuelta o el aviso por sí solos.
"""
import re

import requests
from flask import current_app

from . import ajustes, cobros, correos
from .extensions import db
from .models import Cita, Pago
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


def url_de_pago(cita, monto=None):
    """Crea el cobro y devuelve la dirección a la que se envía al paciente.
    Sin monto, cobra lo definido al reservar; con monto (cobranza), ese saldo."""
    if not current_app.config["MP_ACCESS_TOKEN"]:
        raise PagoError("El pago en línea no está activado.")
    if monto is None and not ajustes.pagos_activos():
        raise PagoError("El pago en línea no está activado.")
    if cita.estado_pago in ("pagado", "sin_costo"):
        raise PagoError("Esta hora ya está pagada.")
    if cita.estado == "cancelada" or (cita.expira and cita.expira < ahora()):
        raise PagoError("El plazo para pagar terminó y la hora se liberó. Reserva de nuevo.")

    if monto is not None:
        cita.monto = min(int(monto), cita.saldo)
        db.session.commit()
    elif cita.monto <= 0:
        cita.monto = min(ajustes.monto_a_pagar(cita.precio), cita.saldo)
        if cita.estado_pago == "por_cobrar":
            cita.estado_pago = "pendiente"
        db.session.commit()
    if cita.monto <= 0:
        raise PagoError("No queda nada por pagar.")

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
    """Consulta un pago y, si está aprobado y corresponde, lo registra en la
    cita. Devuelve la cita o None si el pago no es de una cita."""
    pago_id = str(pago_id or "")
    if not current_app.config["MP_ACCESS_TOKEN"] or not pago_id.isdigit():
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
    if Pago.query.filter_by(medio="mercadopago", referencia=pago_id).first():
        db.session.rollback()
        return cita  # Ya registrado: el aviso llegó dos veces.
    monto = round(float(pago.get("transaction_amount") or 0))
    if pago.get("currency_id") != "CLP" or monto < cita.monto or monto <= 0:
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

    if esperaba_pago and cita.estado_pago == "pendiente":
        cita.estado_pago = "por_cobrar"
    cita.monto = 0
    db.session.add(Pago(cita=cita, paciente_id=cita.paciente_id, profesional_id=cita.profesional_id, monto=monto,
                        medio="mercadopago", fecha=ahora().date(), referencia=pago_id, nota="Pago en línea"))
    db.session.flush()
    db.session.refresh(cita)
    cobros.recalcular(cita)
    cita.expira = None
    if liberada:
        if cita.estado != "cancelada":
            cita.cancelar("sistema", "El pago llegó después del plazo")
    elif cita.estado == "pendiente":
        cita.estado = "confirmada"
    db.session.commit()

    if liberada:
        correos.pago_tardio(cita, monto)
    elif esperaba_pago:
        correos.nueva_cita(cita)
    else:
        correos.pago_recibido(cita, monto)
    return cita
