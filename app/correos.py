"""Avisos al paciente (correo y WhatsApp), al negocio y al profesional.

Los correos salen por SMTP en un hilo aparte para no demorar la página. Sin
SMTP configurado, sólo quedan en el registro (log).
"""
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app, url_for

from . import ajustes, mensajes, whatsapp
from .extensions import db
from .tiempo import ahora, fecha_larga, pesos


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


def _enlace(cita):
    return url_absoluta("publico.cita", token=cita.token)


def _lugar(cita):
    if cita.online:
        if cita.enlace_sesion:
            return f"Sesión online: {cita.enlace_sesion}"
        return "Sesión online: te enviaremos el enlace antes de la hora."
    if cita.sucursal:
        s = cita.sucursal
        lugar = f"Lugar: {s.nombre}" + (f", {s.direccion}" if s.direccion else "")
        if s.indicaciones:
            lugar += f"\n{s.indicaciones}"
        return lugar
    return ""


def _detalle(cita):
    lineas = [
        f"Servicio: {cita.servicio.nombre}",
        f"Con: {cita.profesional.nombre}",
        f"Fecha: {fecha_larga(cita.inicio)}",
    ]
    if _lugar(cita):
        lineas.append(_lugar(cita))
    if cita.estado_pago == "pagado":
        lineas.append(f"Pagado: {pesos(cita.pagado)}")
    return "\n".join(lineas)


def _paciente(cita):
    lineas = [f"Nombre: {cita.nombre}"]
    if cita.rut:
        lineas.append(f"RUT: {cita.rut}")
    if cita.email:
        lineas.append(f"Correo: {cita.email}")
    if cita.telefono:
        lineas.append(f"Teléfono: {cita.telefono}")
    if cita.notas:
        lineas.append(f"Comentario: {cita.notas}")
    return "\n".join(lineas)


def _al_equipo(cita, asunto, intro):
    enviar(
        [ajustes.get("email_aviso"), cita.profesional.email],
        asunto,
        f"{intro}\n\n{_detalle(cita)}\n\n{_paciente(cita)}\n\nVer en Reservared: {url_absoluta('panel.cita', cita_id=cita.id)}",
    )


def _al_paciente(clave, cita, monto=0):
    """Envía al paciente el mensaje `clave` de Ajustes → Mensajes, si está activo."""
    armado = mensajes.armar(clave, cita, _enlace(cita), monto)
    if armado:
        enviar(cita.email, *armado)
        if cita.online and cita.enlace_sesion and "{enlace_sesion}" in mensajes.plantilla(clave)["cuerpo"]:
            cita.enlace_avisado = cita.enlace_sesion
            db.session.commit()


def nueva_cita(cita, avisar_equipo=True):
    """Hora reservada: crea la sesión online si corresponde y avisa por correo
    y WhatsApp."""
    from . import sesiones

    sesiones.asegurar(cita)
    _al_paciente("confirmacion", cita)
    whatsapp.confirmacion(cita, _enlace(cita))
    if avisar_equipo:
        _al_equipo(cita, f"Nueva reserva: {cita.nombre}, {fecha_larga(cita.inicio)}", "Llegó una reserva nueva.")


def enlace_si_falta(cita):
    """Si una cita online recibió (o cambió) su enlace después de avisar al
    paciente, le manda el correo con el enlace nuevo."""
    if (not cita.online or not cita.enlace_sesion or cita.enlace_sesion == cita.enlace_avisado
            or cita.estado not in ("confirmada", "pendiente") or cita.espera_pago or cita.inicio < ahora()):
        return False
    _al_paciente("enlace_sesion", cita)
    return True


def reagendada(cita):
    from . import sesiones

    sesiones.cancelar(cita)
    sesiones.asegurar(cita)
    _al_paciente("reagendada", cita)
    whatsapp.confirmacion(cita, _enlace(cita))
    _al_equipo(cita, f"Hora reagendada: {cita.nombre}, {fecha_larga(cita.inicio)}", "Se movió esta cita.")


def recordatorio(cita):
    _al_paciente("recordatorio", cita)
    whatsapp.recordatorio(cita, _enlace(cita))


def cancelada_por_paciente(cita):
    motivo = f" Motivo: {cita.motivo_cancelacion}." if cita.motivo_cancelacion else ""
    _al_equipo(cita, f"Hora cancelada: {cita.nombre}, {fecha_larga(cita.inicio)}",
               f"El paciente canceló su hora. El horario quedó libre.{motivo}")


def cancelada_por_equipo(cita):
    _al_paciente("cancelada", cita)


def confirmada(cita):
    _al_paciente("confirmada", cita)


def pago_tardio(cita, monto):
    _al_equipo(
        cita,
        f"Pago recibido de una hora ya liberada: {cita.nombre}",
        f"Llegó un pago en línea de {pesos(monto)}, pero después del plazo, y la hora "
        "ya se había liberado. Contacta al paciente para darle otra hora o devolver el pago.",
    )


def pago_recibido(cita, monto):
    _al_paciente("pago_recibido", cita, monto)


def cobro(cita, enlace_pago=""):
    """Recordatorio de saldo pendiente."""
    _al_paciente("cobro", cita)


def restablecer_clave(usuario, enlace):
    enviar(
        usuario.email,
        f"Cambia tu contraseña de Reservared — {_negocio()}",
        f"Hola {usuario.nombre},\n\nPara elegir una contraseña nueva abre este enlace (vale por una hora):\n\n{enlace}\n\n"
        "Si no lo pediste, ignora este correo.",
    )


def acceso_nuevo(usuario, enlace):
    enviar(
        usuario.email,
        f"Tu acceso a Reservared — {_negocio()}",
        f"Hola {usuario.nombre},\n\nYa tienes acceso a Reservared de {_negocio()}.\n\n"
        f"Elige tu contraseña aquí (el enlace vale una hora):\n{enlace}\n\n"
        f"Después entras en: {url_absoluta('panel.entrar')}\nTu usuario es: {usuario.email}",
    )


def marcar_recordatorio(cita):
    cita.recordatorio_enviado = ahora()
