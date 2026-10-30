"""Sesiones online: un Google Meet por cita, o la sala fija del profesional.

Con una cuenta de Google conectada (Ajustes → Google), cada cita online crea un
evento en ese Google Calendar con su enlace de Meet, invitando al paciente y al
profesional. Sin Google, se usa la sala fija del profesional si la tiene.
"""
import base64
import json
import time
from urllib.parse import urlencode

import requests
from flask import current_app

from . import ajustes
from .extensions import db
from .tiempo import ZONA, con_zona

AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
EVENTOS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
PERMISOS = "openid email https://www.googleapis.com/auth/calendar.events"

_acceso = {"token": "", "vence": 0.0}


class GoogleError(Exception):
    pass


def google_configurado():
    c = current_app.config
    return bool(c["GOOGLE_CLIENT_ID"] and c["GOOGLE_CLIENT_SECRET"])


def google_conectado():
    return google_configurado() and bool(ajustes.get("google_refresh_token"))


def url_autorizacion(volver, estado):
    return AUTORIZAR + "?" + urlencode({
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "redirect_uri": volver,
        "response_type": "code",
        "scope": PERMISOS,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": estado,
    })


def conectar(codigo, volver):
    """Cambia el código que entrega Google por un permiso duradero y lo guarda."""
    r = requests.post(TOKEN, timeout=20, data={
        "code": codigo,
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": volver,
        "grant_type": "authorization_code",
    })
    datos = r.json() if r.content else {}
    if r.status_code != 200 or not datos.get("refresh_token"):
        raise GoogleError(datos.get("error_description") or datos.get("error") or "Google no entregó el permiso.")
    cuenta = ""
    if datos.get("id_token"):
        try:
            carga = datos["id_token"].split(".")[1]
            cuenta = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4))).get("email", "")
        except (IndexError, ValueError):
            pass
    ajustes.guardar({"google_refresh_token": datos["refresh_token"], "google_cuenta": cuenta})
    _acceso.update(token=datos.get("access_token", ""), vence=time.time() + int(datos.get("expires_in", 0)) - 60)


def desconectar():
    ajustes.guardar({"google_refresh_token": "", "google_cuenta": ""})
    _acceso.update(token="", vence=0.0)


def _token():
    if _acceso["token"] and _acceso["vence"] > time.time():
        return _acceso["token"]
    try:
        r = requests.post(TOKEN, timeout=20, data={
            "refresh_token": ajustes.get("google_refresh_token"),
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "grant_type": "refresh_token",
        })
    except requests.RequestException:
        raise GoogleError("No se pudo conectar con Google.")
    datos = r.json() if r.content else {}
    if r.status_code != 200 or not datos.get("access_token"):
        raise GoogleError("Google rechazó el permiso. Vuelve a conectar la cuenta en Ajustes.")
    _acceso.update(token=datos["access_token"], vence=time.time() + int(datos.get("expires_in", 3600)) - 60)
    return _acceso["token"]


def _crear_meet(cita):
    invitados = [{"email": cita.email, "displayName": cita.nombre}]
    if cita.profesional.email:
        invitados.append({"email": cita.profesional.email, "displayName": cita.profesional.nombre})
    evento = {
        "summary": f"{cita.servicio.nombre}: {cita.nombre} con {cita.profesional.nombre}",
        "description": f"Reserva hecha en {current_app.config['NOMBRE_NEGOCIO']}.",
        "start": {"dateTime": con_zona(cita.inicio).isoformat(), "timeZone": str(ZONA)},
        "end": {"dateTime": con_zona(cita.fin).isoformat(), "timeZone": str(ZONA)},
        "attendees": invitados,
        "conferenceData": {"createRequest": {"requestId": cita.token[:40], "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
        "reminders": {"useDefault": True},
    }
    params = {"conferenceDataVersion": 1, "sendUpdates": "all" if ajustes.get("google_invitar") else "none"}
    cabeceras = {"Authorization": "Bearer " + _token()}
    try:
        r = requests.post(EVENTOS, params=params, json=evento, headers=cabeceras, timeout=20)
        datos = r.json() if r.content else {}
        if r.status_code not in (200, 201):
            raise GoogleError(datos.get("error", {}).get("message", f"código {r.status_code}"))
        enlace = datos.get("hangoutLink", "")
        # A veces Google demora un instante en crear la sala.
        intentos = 0
        while not enlace and intentos < 3:
            time.sleep(1)
            intentos += 1
            r2 = requests.get(f"{EVENTOS}/{datos['id']}", headers=cabeceras, timeout=20)
            enlace = (r2.json() if r2.content else {}).get("hangoutLink", "")
    except requests.RequestException:
        raise GoogleError("No se pudo conectar con Google.")
    return datos["id"], enlace


def asegurar(cita):
    """Si la cita es online y todavía no tiene enlace, se lo crea. Nunca falla:
    si Google no responde, queda sin enlace y se puede crear desde el panel."""
    if not cita.servicio.online or cita.estado == "cancelada" or cita.enlace_sesion or cita.espera_pago:
        return
    if google_conectado():
        try:
            cita.google_evento_id, cita.enlace_sesion = _crear_meet(cita)
        except GoogleError as e:
            current_app.logger.warning("No se creó el Meet de la cita %s: %s", cita.id, e)
    if not cita.enlace_sesion and cita.profesional.enlace_sala:
        cita.enlace_sesion = cita.profesional.enlace_sala
    db.session.commit()


def cancelar(cita):
    """Borra el evento de Google (y avisa a los invitados)."""
    if not cita.google_evento_id or not google_conectado():
        return
    try:
        requests.delete(
            f"{EVENTOS}/{cita.google_evento_id}",
            params={"sendUpdates": "all" if ajustes.get("google_invitar") else "none"},
            headers={"Authorization": "Bearer " + _token()},
            timeout=20,
        )
    except (requests.RequestException, GoogleError) as e:
        current_app.logger.warning("No se borró el evento de Google de la cita %s: %s", cita.id, e)
        return
    cita.google_evento_id = ""
    cita.enlace_sesion = ""
    db.session.commit()

