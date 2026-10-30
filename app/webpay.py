"""Pago con Webpay Plus (Transbank).

1. ``iniciar`` crea la transacción y entrega la dirección y el token: el
   paciente se envía a Webpay con un formulario (token_ws).
2. Webpay lo devuelve a /pago/webpay; ``confirmar`` cierra la transacción y,
   si quedó autorizada por el monto correcto, registra el pago en la cita.

Con WEBPAY_AMBIENTE=integracion y sin código propio, usa el ambiente de
pruebas de Transbank (tarjetas de prueba, sin cobrar de verdad).
"""
import secrets

import requests
from flask import current_app

from . import cobros, correos
from .extensions import db
from .models import Pago, PagoEnLinea
from .reservas import _candado
from .tiempo import ahora

RUTA = "/rswebpaytransaction/api/webpay/v1.2/transactions"
SERVIDORES = {"produccion": "https://webpay3g.transbank.cl", "integracion": "https://webpay3gint.transbank.cl"}
# Credenciales públicas de prueba que publica Transbank.
PRUEBA = ("597055555532", "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C")


class WebpayError(Exception):
    pass


def disponible():
    """Con código de comercio, o en modo de pruebas pedido a propósito
    (WEBPAY_AMBIENTE=integracion). Nunca cae en pruebas por olvido: ahí los
    pacientes "pagarían" con tarjetas de prueba."""
    c = current_app.config
    return bool(c["WEBPAY_CODIGO_COMERCIO"] and c["WEBPAY_LLAVE_SECRETA"]) or c["WEBPAY_AMBIENTE"] == "integracion"


def _credenciales():
    c = current_app.config
    if c["WEBPAY_CODIGO_COMERCIO"] and c["WEBPAY_LLAVE_SECRETA"]:
        return c["WEBPAY_CODIGO_COMERCIO"], c["WEBPAY_LLAVE_SECRETA"], c["WEBPAY_AMBIENTE"]
    if c["WEBPAY_AMBIENTE"] == "integracion":
        return PRUEBA[0], PRUEBA[1], "integracion"
    raise WebpayError("Falta el código de comercio de Webpay.")


def en_pruebas():
    return _credenciales()[2] != "produccion"


def _pedir(metodo, ruta, json=None):
    codigo, llave, ambiente = _credenciales()
    try:
        r = requests.request(metodo, SERVIDORES[ambiente] + RUTA + ruta, json=json, timeout=30, headers={
            "Tbk-Api-Key-Id": codigo, "Tbk-Api-Key-Secret": llave, "Content-Type": "application/json"})
    except requests.RequestException:
        raise WebpayError("No se pudo conectar con Webpay. Intenta de nuevo.")
    datos = r.json() if r.content else {}
    if r.status_code >= 300:
        raise WebpayError(f"Webpay rechazó la solicitud ({datos.get('error_message', r.status_code)}).")
    return datos


def iniciar(cita, monto):
    """Devuelve (url, token) para enviar al paciente a pagar."""
    orden = f"rr{cita.id}x{secrets.token_hex(5)}"[:26]
    r = _pedir("POST", "", {
        "buy_order": orden,
        "session_id": str(cita.id),
        "amount": int(monto),
        "return_url": correos.url_absoluta("publico.webpay_volver"),
    })
    if not r.get("token") or not r.get("url"):
        raise WebpayError("Webpay no entregó el enlace de pago.")
    db.session.add(PagoEnLinea(cita_id=cita.id, pasarela="webpay", orden=orden, token=r["token"], monto=int(monto)))
    db.session.commit()
    return r["url"], r["token"]


def confirmar(token):
    """Cierra la transacción. Devuelve (cita, aprobado)."""
    intento = PagoEnLinea.query.filter_by(pasarela="webpay", token=token).first()
    if not intento:
        return None, False
    if intento.estado != "iniciado":
        return intento.cita, intento.estado == "aprobado"
    r = _pedir("PUT", f"/{token}")
    aprobado = (r.get("status") == "AUTHORIZED" and r.get("response_code") == 0
                and int(r.get("amount") or 0) == intento.monto and r.get("buy_order") == intento.orden)
    return _registrar(intento, aprobado, r.get("authorization_code", "")), aprobado


def anular_intento(orden):
    """El paciente abandonó Webpay (volvió con TBK_TOKEN)."""
    intento = PagoEnLinea.query.filter_by(pasarela="webpay", orden=orden).first()
    if intento and intento.estado == "iniciado":
        intento.estado = "rechazado"
        db.session.commit()
    return intento.cita if intento else None


def _registrar(intento, aprobado, autorizacion):
    _candado()
    cita = intento.cita
    if not aprobado:
        intento.estado = "rechazado"
        db.session.commit()
        return cita
    intento.estado = "aprobado"
    esperaba_pago = cita.expira is not None
    liberada = cita.estado == "cancelada"
    if esperaba_pago and cita.estado_pago == "pendiente":
        cita.estado_pago = "por_cobrar"
    cita.monto = 0
    db.session.add(Pago(cita=cita, paciente_id=cita.paciente_id, profesional_id=cita.profesional_id, monto=intento.monto,
                        medio="webpay", fecha=ahora().date(), referencia=f"{intento.orden} · aut. {autorizacion}"[:120],
                        nota="Pago en línea"))
    db.session.flush()
    db.session.refresh(cita)
    cobros.recalcular(cita)
    cita.expira = None
    if not liberada and cita.estado == "pendiente":
        cita.estado = "confirmada"
    db.session.commit()
    if liberada:
        correos.pago_tardio(cita, intento.monto)
    elif esperaba_pago:
        correos.nueva_cita(cita)
    else:
        correos.pago_recibido(cita, intento.monto)
    return cita
