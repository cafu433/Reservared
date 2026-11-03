"""Mensajes al paciente que el negocio edita en Ajustes → Mensajes.

Cada mensaje tiene asunto y cuerpo con campos entre llaves ({nombre},
{fecha}…) y bloques que aparecen sólo en un tipo de cita:

    [online]Entra a tu sesión aquí: {enlace_sesion}[/online]
    [presencial]Te esperamos en {direccion}.[/presencial]
"""
import re

from flask import current_app

from . import ajustes
from .tiempo import DIAS, MESES, fecha_larga, pesos

PLANTILLAS = {
    "confirmacion": {
        "nombre": "Confirmación de la reserva",
        "cuando": "Apenas se reserva una hora (o cuando se confirma el pago, si es obligatorio).",
        "asunto": "Tu hora en {negocio}: {fecha} a las {hora}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Tu hora quedó reservada.\n\n"
            "{servicio} con {profesional}\n"
            "{fecha} a las {hora}\n"
            "[presencial]Lugar: {lugar}\n{indicaciones}[/presencial]"
            "[online]Es una sesión online. Entra desde este enlace a la hora de tu cita:\n{enlace_sesion}[/online]\n\n"
            "{mensaje}\n\n"
            "Para ver, reagendar o cancelar tu hora: {enlace_cita}\n\n"
            "{negocio}"
        ),
    },
    "enlace_sesion": {
        "nombre": "Enlace de la sesión online",
        "cuando": "Cuando una cita online recibe su enlace después de confirmada (por ejemplo, al crear el Meet desde el panel).",
        "asunto": "Tu enlace para la sesión del {fecha}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Este es el enlace para tu sesión online de {servicio} con {profesional}, "
            "el {fecha} a las {hora}:\n\n"
            "{enlace_sesion}\n\n"
            "Te recomendamos conectarte unos minutos antes, en un lugar tranquilo y con buena conexión.\n\n"
            "{negocio}"
        ),
    },
    "recordatorio": {
        "nombre": "Recordatorio del día antes",
        "cuando": "24 horas antes de la cita.",
        "asunto": "Recordatorio: tu hora es mañana, {fecha} a las {hora}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Te recordamos tu hora de {servicio} con {profesional}, el {fecha} a las {hora}.\n"
            "[presencial]Lugar: {lugar}\n{indicaciones}[/presencial]"
            "[online]Entra a la sesión desde este enlace: {enlace_sesion}[/online]\n\n"
            "Si no puedes asistir, cancela o reagenda aquí: {enlace_cita}\n\n"
            "{negocio}"
        ),
    },
    "reagendada": {
        "nombre": "Cita reagendada",
        "cuando": "Cuando el equipo mueve la cita a otro día u hora.",
        "asunto": "Tu hora cambió: {fecha} a las {hora}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Tu hora quedó en un nuevo horario:\n\n"
            "{servicio} con {profesional}\n"
            "{fecha} a las {hora}\n"
            "[presencial]Lugar: {lugar}[/presencial]"
            "[online]Enlace de la sesión: {enlace_sesion}[/online]\n\n"
            "Ver o cancelar tu hora: {enlace_cita}\n\n"
            "{negocio}"
        ),
    },
    "confirmada": {
        "nombre": "Cita confirmada por el equipo",
        "cuando": "Cuando el equipo cambia una cita pendiente a confirmada.",
        "asunto": "Tu hora está confirmada — {negocio}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Tu hora de {servicio} con {profesional} del {fecha} a las {hora} está confirmada.\n"
            "[online]Enlace de la sesión: {enlace_sesion}[/online]\n\n"
            "{negocio}"
        ),
    },
    "cancelada": {
        "nombre": "Cita cancelada por el equipo",
        "cuando": "Cuando el equipo cancela la cita.",
        "asunto": "Tu hora fue cancelada — {negocio}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Tu hora de {servicio} del {fecha} a las {hora} fue cancelada.\n"
            "Si quieres otra hora, puedes reservar de nuevo o escribirnos.\n\n"
            "{negocio}"
        ),
    },
    "cobro": {
        "nombre": "Recordatorio de pago",
        "cuando": "Cuando se envía un recordatorio de saldo desde Cobranza o desde la cita.",
        "asunto": "Saldo pendiente — {negocio}",
        "cuerpo": (
            "Hola {nombre},\n\n"
            "Queda un saldo de {saldo} de tu atención del {fecha}.\n\n"
            "Puedes pagarlo en línea aquí: {enlace_cita}\n\n"
            "{negocio}"
        ),
    },
    "pago_recibido": {
        "nombre": "Pago recibido",
        "cuando": "Cuando llega un pago en línea (Webpay o Mercado Pago).",
        "asunto": "Recibimos tu pago — {negocio}",
        "cuerpo": "Hola {nombre},\n\nRecibimos tu pago de {monto}. Gracias.\n\n{servicio}, {fecha} a las {hora}.\n\n{negocio}",
    },
    "whatsapp_cita": {
        "nombre": "WhatsApp: datos de la hora",
        "cuando": "Texto del botón \"Enviar la hora por WhatsApp\" en cada cita.",
        "asunto": "",
        "cuerpo": (
            "Hola {nombre}, te escribimos de {negocio}. Tu hora es el {fecha} a las {hora} con {profesional} ({servicio})."
            "[presencial] Lugar: {lugar}.[/presencial][online] Enlace de la sesión: {enlace_sesion}[/online]"
            " Para ver o cancelar tu hora: {enlace_cita}"
        ),
    },
    "whatsapp_cobro": {
        "nombre": "WhatsApp: cobro de saldo",
        "cuando": "Texto del botón \"Cobrar por WhatsApp\".",
        "asunto": "",
        "cuerpo": "Hola {nombre}, te escribimos de {negocio}. Queda un saldo de {saldo} de tu atención del {fecha}. Puedes pagarlo aquí: {enlace_cita}",
    },
}

CAMPOS = {
    "nombre": "Primer nombre del paciente",
    "nombre_completo": "Nombre completo",
    "fecha": "Día de la cita (martes 3 de noviembre)",
    "hora": "Hora de la cita (09:30)",
    "servicio": "Servicio",
    "profesional": "Profesional",
    "modalidad": "Presencial u online",
    "lugar": "Sucursal y dirección",
    "direccion": "Sólo la dirección",
    "indicaciones": "Indicaciones de la sucursal",
    "enlace_sesion": "Enlace de la sesión online (Meet o sala)",
    "enlace_cita": "Enlace para ver, pagar o cancelar la hora",
    "valor": "Valor de la cita",
    "saldo": "Saldo por pagar",
    "monto": "Monto del pago recibido",
    "mensaje": "El \"Mensaje al reservar\" de Ajustes",
    "negocio": "Nombre del centro",
}

_CAMPO = re.compile(r"\{([a-z_]+)\}")
_BLOQUE = re.compile(r"\[(online|presencial)\](.*?)\[/\1\]", re.S)


def guardadas():
    return ajustes.get("mensajes") or {}


def plantilla(clave):
    """Asunto, cuerpo y si está activo, con lo guardado encima de lo original."""
    base = PLANTILLAS[clave]
    propio = guardadas().get(clave) or {}
    return {
        "asunto": propio.get("asunto", base["asunto"]),
        "cuerpo": propio.get("cuerpo", base["cuerpo"]),
        "activo": propio.get("activo", True),
        "editado": bool(propio.get("asunto") is not None or propio.get("cuerpo") is not None),
    }


def datos_de(cita, enlace_cita="", monto=0):
    f = cita.inicio
    suc = cita.sucursal
    lugar = ""
    if not cita.online and suc:
        lugar = suc.nombre + (f", {suc.direccion}" if suc.direccion else "")
    return {
        "nombre": (cita.nombre or "").split()[0] if cita.nombre else "",
        "nombre_completo": cita.nombre or "",
        "fecha": f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]}",
        "hora": f.strftime("%H:%M"),
        "servicio": cita.servicio.nombre,
        "profesional": cita.profesional.nombre,
        "modalidad": "Online" if cita.online else "Presencial",
        "lugar": lugar,
        "direccion": suc.direccion if suc and not cita.online else "",
        "indicaciones": suc.indicaciones if suc and not cita.online else "",
        "enlace_sesion": cita.enlace_sesion or "te lo enviaremos antes de la hora",
        "enlace_cita": enlace_cita,
        "valor": pesos(cita.precio) if cita.precio else "",
        "saldo": pesos(cita.saldo),
        "monto": pesos(monto),
        "mensaje": ajustes.get("mensaje_confirmacion") or "",
        "negocio": current_app.config["NOMBRE_NEGOCIO"],
        "_online": cita.online,
    }


def rellenar(texto, datos):
    online = datos.get("_online", False)

    def bloque(m):
        return m.group(2) if (m.group(1) == "online") == online else ""

    texto = _BLOQUE.sub(bloque, texto or "")
    texto = _CAMPO.sub(lambda m: str(datos.get(m.group(1), m.group(0))), texto)
    # Sin líneas vacías de más cuando un campo o bloque quedó en blanco.
    lineas = [l.rstrip() for l in texto.split("\n")]
    limpio, vacias = [], 0
    for l in lineas:
        vacias = vacias + 1 if not l.strip() else 0
        if vacias <= 1:
            limpio.append(l)
    return "\n".join(limpio).strip()


def armar(clave, cita, enlace_cita="", monto=0):
    """(asunto, cuerpo) listos para enviar, o None si el mensaje está desactivado."""
    p = plantilla(clave)
    if not p["activo"]:
        return None
    datos = datos_de(cita, enlace_cita, monto)
    return rellenar(p["asunto"], datos), rellenar(p["cuerpo"], datos)


def validar(texto):
    """Campos que no existen (probablemente mal escritos)."""
    return sorted({c for c in _CAMPO.findall(texto or "") if c not in CAMPOS})


def guardar(clave, asunto, cuerpo, activo):
    todas = dict(guardadas())
    todas[clave] = {"asunto": asunto, "cuerpo": cuerpo, "activo": bool(activo)}
    ajustes.guardar({"mensajes": todas})


def restablecer(clave):
    todas = dict(guardadas())
    activo = (todas.get(clave) or {}).get("activo", True)
    todas[clave] = {"activo": activo}
    ajustes.guardar({"mensajes": todas})
