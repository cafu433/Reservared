"""Lo que ve el paciente: la página de reserva, la página de su cita y la API
que usa el formulario. También el aviso de pagos de Mercado Pago."""
import hashlib
import time
from collections import defaultdict
from datetime import date, timedelta

from flask import abort, current_app, jsonify, redirect, render_template, request, url_for

from .. import ajustes, correos, pagos, sesiones
from ..disponibilidad import calcular
from ..extensions import csrf, db
from ..models import Cita, Profesional, Servicio
from ..reservas import ReservaError, cancelable, liberar_horas_sin_pagar, reservar
from ..tiempo import ahora, fecha_larga, pesos
from . import bp

# Límite simple por IP: 8 reservas por hora en cada proceso.
_intentos = defaultdict(list)


def _limite_superado():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    clave = hashlib.sha256(ip.encode()).hexdigest()
    hace_una_hora = time.time() - 3600
    _intentos[clave] = [t for t in _intentos[clave] if t > hace_una_hora]
    if len(_intentos[clave]) >= 8:
        return True
    _intentos[clave].append(time.time())
    return False


@bp.get("/")
def inicio():
    return redirect(url_for("publico.reservar_pagina"))


@bp.get("/reservar")
def reservar_pagina():
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.nombre).all()
    profesionales = Profesional.query.filter_by(activo=True).order_by(Profesional.nombre).all()
    pago_modo = ajustes.get("pago_modo") if ajustes.pagos_activos() else "ninguno"
    config = {
        "api": request.script_root + "/api/",
        "pedirRut": bool(ajustes.get("pedir_rut")),
        "pagoModo": pago_modo,
        "pagoEsAbono": int(ajustes.get("pago_porcentaje")) < 100,
        "hoy": ahora().date().isoformat(),
        "diasMaximo": int(ajustes.get("dias_maximo")),
        "servicios": [
            {
                "id": s.id,
                "nombre": s.nombre,
                "descripcion": s.descripcion,
                "duracion": s.duracion,
                "online": s.online,
                "precio": pesos(s.precio) if s.precio else "",
                "pago": pesos(ajustes.monto_a_pagar(s.precio)) if pago_modo != "ninguno" and ajustes.monto_a_pagar(s.precio) > 0 else "",
            }
            for s in servicios
        ],
        "profesionales": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "titulo": p.titulo,
                "servicios": [s.id for s in p.servicios] or None,
            }
            for p in profesionales
        ],
    }
    return render_template(
        "publico/reservar.html",
        config=config,
        color=ajustes.get("color"),
        incrustado=request.args.get("embed") == "1",
        sin_datos=not servicios or not profesionales,
    )


@bp.get("/api/disponibilidad")
def api_disponibilidad():
    liberar_horas_sin_pagar()
    servicio = db.session.get(Servicio, request.args.get("servicio", type=int) or 0)
    if not servicio or not servicio.activo:
        return jsonify(error="Servicio no encontrado."), 404
    prof_id = request.args.get("profesional", type=int) or 0
    if prof_id:
        p = db.session.get(Profesional, prof_id)
        if not p or not p.activo:
            return jsonify(error="Profesional no encontrado."), 404
        profesionales = [p]
    else:
        profesionales = Profesional.query.filter_by(activo=True).all()
    try:
        desde = date.fromisoformat(request.args.get("desde", ""))
        hasta = date.fromisoformat(request.args.get("hasta", ""))
    except ValueError:
        return jsonify(error="Fechas inválidas."), 400
    hasta = min(hasta, desde + timedelta(days=42))
    dias = calcular(servicio, profesionales, desde, hasta)
    resp = jsonify(dias={d.isoformat(): list(horas) for d, horas in dias.items()})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/api/reservas")
@csrf.exempt
def api_reservar():
    datos = request.get_json(silent=True) or {}
    if datos.get("sitio_web"):  # Campo trampa: las personas no lo ven.
        return jsonify(message="No se pudo reservar."), 400
    if _limite_superado():
        return jsonify(message="Hiciste muchas reservas seguidas. Espera una hora o escríbenos."), 429
    try:
        cita = reservar(datos)
    except ReservaError as e:
        return jsonify(message=str(e), code=e.codigo), 400

    resp = {
        "ok": True,
        "enlace": url_for("publico.cita", token=cita.token),
        "mensaje": ajustes.get("mensaje_confirmacion"),
        "cita": {
            "servicio": cita.servicio.nombre,
            "profesional": cita.profesional.nombre,
            "fecha": fecha_larga(cita.inicio),
            "online": cita.servicio.online,
        },
    }

    if cita.estado_pago == "pendiente":
        try:
            resp["pago_url"] = pagos.url_de_pago(cita)
        except pagos.PagoError as e:
            if cita.expira:
                # Sin pago no hay reserva: se libera la hora.
                cita.estado, cita.estado_pago = "cancelada", "vencido"
                db.session.commit()
                return jsonify(message=f"{e} Tu hora no quedó reservada.", code="pago"), 502
            cita.estado_pago, cita.monto = "sin_pago", 0
            db.session.commit()
            resp["aviso"] = "Tu hora quedó reservada, pero no pudimos abrir el pago en línea. Puedes pagar en el lugar."
        if cita.expira:
            return jsonify(resp)  # Los correos salen cuando se confirme el pago.

    correos.nueva_cita(cita)
    resp["cita"]["sesion"] = cita.enlace_sesion
    return jsonify(resp)


MENSAJES = {
    "pagado": ("ok", "Recibimos tu pago. Tu hora está confirmada y te enviamos el detalle por correo."),
    "pago_en_revision": ("", "Tu pago está en revisión. Cuando Mercado Pago lo apruebe te llegará un correo."),
    "pago_fallido": ("error", "El pago no se completó. Puedes intentarlo de nuevo."),
    "pago_no_disponible": ("error", "No se pudo abrir el pago. Si el plazo terminó, reserva una hora nueva."),
    "cancelada": ("ok", "Cancelamos tu hora. Gracias por avisar."),
    "no_cancelable": ("error", "Esta hora ya no se puede cancelar en línea. Escríbenos."),
}


@bp.route("/cita/<token>", methods=["GET", "POST"])
@csrf.exempt
def cita(token):
    c = Cita.query.filter_by(token=token).first()
    if not c:
        abort(404)
    aqui = url_for("publico.cita", token=token)

    # Vuelta desde Mercado Pago.
    if "payment_id" in request.args or "collection_status" in request.args:
        estado = request.args.get("collection_status") or request.args.get("status") or ""
        resultado = "pago_fallido"
        if estado == "approved" and request.args.get("payment_id"):
            try:
                pagada = pagos.verificar(request.args["payment_id"], c)
                resultado = "pagado" if pagada and pagada.estado_pago == "pagado" else "pago_en_revision"
            except pagos.PagoError:
                resultado = "pago_en_revision"
        elif estado in ("pending", "in_process"):
            resultado = "pago_en_revision"
        return redirect(f"{aqui}?r={resultado}")

    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "pagar":
            try:
                return redirect(pagos.url_de_pago(c))
            except pagos.PagoError:
                return redirect(f"{aqui}?r=pago_no_disponible")
        if accion == "cancelar":
            if cancelable(c):
                c.estado = "cancelada"
                db.session.commit()
                sesiones.cancelar(c)
                correos.cancelada_por_paciente(c)
                return redirect(f"{aqui}?r=cancelada")
            return redirect(f"{aqui}?r=no_cancelable")
        abort(400)

    return render_template(
        "publico/cita.html",
        c=c,
        mensaje=MENSAJES.get(request.args.get("r", "")),
        puede_pagar=c.estado_pago == "pendiente" and c.estado != "cancelada" and ajustes.pagos_activos(),
        puede_cancelar=cancelable(c),
        color=ajustes.get("color"),
    )


@bp.route("/webhooks/mercadopago", methods=["GET", "POST"])
@csrf.exempt
def aviso_mercadopago():
    cuerpo = request.get_json(silent=True) or {}
    tipo = request.args.get("type") or request.args.get("topic") or cuerpo.get("type")
    if tipo != "payment":
        return jsonify(ok=True)
    pago_id = request.args.get("data.id") or (cuerpo.get("data") or {}).get("id") or request.args.get("id")
    if not pago_id or not str(pago_id).isdigit():
        return jsonify(ok=True)
    try:
        pagos.verificar(str(pago_id))
    except pagos.PagoRedError:
        return jsonify(ok=False), 500  # Mercado Pago vuelve a avisar más tarde.
    except pagos.PagoError:
        current_app.logger.warning("Aviso de pago %s no verificado", pago_id)
    return jsonify(ok=True)
