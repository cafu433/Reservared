"""WhatsApp: envío automático con la API de WhatsApp Business (Meta) y enlaces
wa.me para enviar a mano desde el teléfono del equipo.

Meta sólo deja iniciar una conversación con plantillas aprobadas. Las dos que
usa Reservared llevan cuatro datos, en este orden: nombre del paciente, fecha y
hora, profesional y enlace de la reserva. El texto sugerido está en el README.
"""
import re
from urllib.parse import quote

import requests
from flask import current_app

from .tiempo import fecha_larga

API = "https://graph.facebook.com/v21.0/{numero}/messages"


def configurado():
    c = current_app.config
    return bool(c["WHATSAPP_TOKEN"] and c["WHATSAPP_NUMERO_ID"])


def numero(telefono):
    """'+56 9 1234 5678' o '912345678' → '56912345678'. Vacío si no parece un número."""
    d = re.sub(r"\D", "", telefono or "")
    if len(d) == 9 and d.startswith("9"):
        d = "56" + d
    if len(d) == 8:  # fijo de Santiago sin el 2
        d = "562" + d
    return d if 10 <= len(d) <= 15 else ""


def _datos(cita, enlace):
    return [cita.nombre.split()[0] if cita.nombre else "", fecha_larga(cita.inicio), cita.profesional.nombre, enlace]


def _enviar_plantilla(cita, plantilla, enlace):
    if not configurado():
        return False
    destino = numero(cita.telefono)
    if not destino:
        return False
    c = current_app.config
    cuerpo = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": {
            "name": plantilla,
            "language": {"code": c["WHATSAPP_IDIOMA"]},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": t} for t in _datos(cita, enlace)]}],
        },
    }
    try:
        r = requests.post(API.format(numero=c["WHATSAPP_NUMERO_ID"]), json=cuerpo, timeout=15,
                          headers={"Authorization": "Bearer " + c["WHATSAPP_TOKEN"]})
    except requests.RequestException:
        current_app.logger.warning("WhatsApp no respondió (cita %s)", cita.id)
        return False
    if r.status_code >= 300:
        current_app.logger.warning("WhatsApp rechazó el mensaje de la cita %s: %s", cita.id, r.text[:300])
        return False
    return True


def confirmacion(cita, enlace):
    return _enviar_plantilla(cita, current_app.config["WHATSAPP_PLANTILLA_CONFIRMACION"], enlace)


def recordatorio(cita, enlace):
    return _enviar_plantilla(cita, current_app.config["WHATSAPP_PLANTILLA_RECORDATORIO"], enlace)


def enlace_manual(telefono, texto):
    """Abre WhatsApp (teléfono o web) con el mensaje escrito, listo para enviar."""
    destino = numero(telefono)
    return f"https://wa.me/{destino}?text={quote(texto)}" if destino else ""


def texto_cita(cita, enlace, negocio):
    from . import mensajes

    armado = mensajes.armar("whatsapp_cita", cita, enlace)
    return armado[1] if armado else ""


def texto_cobro(cita, enlace, negocio, saldo_texto):
    from . import mensajes

    armado = mensajes.armar("whatsapp_cobro", cita, enlace)
    return armado[1] if armado else ""
