"""Correos al paciente, al negocio y al profesional.

Se envían por SMTP en un hilo aparte para no demorar la página. Sin SMTP
configurado, sólo quedan en el registro (log).
"""
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app, url_for

from . import ajustes
from .tiempo import fecha_larga, pesos


def url_absoluta(endpoint, **valores):
    base = current_app.config["URL_PUBLICA"]
    if base:
        return base + url_for(endpoint, **valores)
    return url_for(endpoint, _external=True, **valores)


def _mandar(config, para, asunto, cuerpo):
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr((config["NOMBRE_NEGOCIO"], config["CORREO_REMITENTE"] or config["SMTP_USUARIO"]))
    msg["To"] = ", ".join(para)
    msg.set_content(cuerpo)
    with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PUERTO"], timeout=20) as s:
        s.starttls()
        if config["SMTP_USUARIO"]:
            s.login(config["SMTP_USUARIO"], config["SMTP_CLAVE"])
        s.send_message(msg)


def enviar(para, asunto, cuerpo):
    para = sorted({p.strip() for p in (para if isinstance(para, (list, tuple, set)) else [para]) if p and "@" in p})
    if not para:
        return
    app = current_app._get_current_object()
    if app.testing:
        app.extensions.setdefault("correos_enviados", []).append({"para": para, "asunto": asunto, "cuerpo": cuerpo})
        return
    if not app.config["SMTP_HOST"]:
        app.logger.warning("Correo sin enviar (falta SMTP_HOST): %s → %s", asunto, para)
        return
    config = dict(app.config)

    def trabajo():
        try:
            _mandar(config, para, asunto, cuerpo)
        except Exception:
            app.logger.exception("No se pudo enviar el correo %r a %s", asunto, para)

    threading.Thread(target=trabajo, daemon=True).start()


def _negocio():
    return current_app.config["NOMBRE_NEGOCIO"]


def _detalle(cita):
    lineas = [
        f"Servicio: {cita.servicio.nombre}",
        f"Con: {cita.profesional.nombre}",
        f"Fecha: {fecha_larga(cita.inicio)}",
    ]
    if cita.enlace_sesion:
        lineas.append(f"Sesión online: {cita.enlace_sesion}")
    elif cita.servicio.online:
        lineas.append("Sesión online: te enviaremos el enlace antes de la hora.")
    if cita.estado_pago == "pagado":
        lineas.append(f"Pagado: {pesos(cita.monto)}")
    return "\n".join(lineas)


def _paciente(cita):
    lineas = [f"Nombre: {cita.nombre}"]
    if cita.rut:
        lineas.append(f"RUT: {cita.rut}")
    lineas.append(f"Correo: {cita.email}")
    if cita.telefono:
        lineas.append(f"Teléfono: {cita.telefono}")
    if cita.notas:
        lineas.append(f"Comentario: {cita.notas}")
    return "\n".join(lineas)


def _al_equipo(cita, asunto, intro):
    enlace = url_absoluta("panel.cita", cita_id=cita.id)
    enviar(
        [ajustes.get("email_aviso"), cita.profesional.email],
        asunto,
        f"{intro}\n\n{_detalle(cita)}\n\n{_paciente(cita)}\n\nVer en Reservared: {enlace}",
    )


def nueva_cita(cita):
    """Hora reservada y confirmada (o sin pago pendiente): crea la sesión online
    si corresponde y avisa a todos."""
    from . import sesiones

    sesiones.asegurar(cita)
    enlace = url_absoluta("publico.cita", token=cita.token)
    enviar(
        cita.email,
        f"Tu hora en {_negocio()}: {fecha_larga(cita.inicio)}",
        f"Hola {cita.nombre},\n\nTu hora quedó reservada.\n\n{_detalle(cita)}\n\n"
        f"{ajustes.get('mensaje_confirmacion')}\n\nVer o cancelar tu hora: {enlace}\n\n{_negocio()}",
    )
    _al_equipo(cita, f"Nueva reserva: {cita.nombre}, {fecha_larga(cita.inicio)}", "Llegó una reserva nueva.")


def cancelada_por_paciente(cita):
    _al_equipo(cita, f"Hora cancelada: {cita.nombre}, {fecha_larga(cita.inicio)}",
               "El paciente canceló su hora. El horario quedó libre.")


def pago_tardio(cita):
    _al_equipo(
        cita,
        f"Pago recibido de una hora ya liberada: {cita.nombre}",
        f"Mercado Pago confirmó el pago de {pesos(cita.monto)}, pero llegó después del plazo y la hora "
        "ya se había liberado. Contacta al paciente para darle otra hora o devolver el pago.",
    )


def estado_cambiado(cita):
    if cita.estado == "confirmada":
        asunto, texto = "Tu hora está confirmada", "Tu hora está confirmada."
    elif cita.estado == "cancelada":
        asunto, texto = "Tu hora fue cancelada", "Tu hora fue cancelada. Si quieres otra, puedes reservar de nuevo o escribirnos."
    else:
        return
    enviar(cita.email, f"{asunto} — {_negocio()}", f"Hola {cita.nombre},\n\n{texto}\n\n{_detalle(cita)}\n\n{_negocio()}")


def restablecer_clave(usuario, enlace):
    enviar(
        usuario.email,
        f"Cambia tu contraseña de Reservared — {_negocio()}",
        f"Hola {usuario.nombre},\n\nPara elegir una contraseña nueva abre este enlace (vale por una hora):\n\n{enlace}\n\n"
        "Si no lo pediste, ignora este correo.",
    )
