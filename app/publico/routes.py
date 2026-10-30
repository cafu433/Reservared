"""Lo que ve el paciente: la página de reserva, la página de su cita y la API
que usa el formulario. También los retornos de Webpay y Mercado Pago, y la
tarea de recordatorios."""
import hashlib
import hmac
import time
from collections import defaultdict
from datetime import date, timedelta

from flask import abort, current_app, jsonify, redirect, render_template, request, url_for

from .. import ajustes, correos, pagos, sesiones, webpay
from ..disponibilidad import calcular
from ..extensions import csrf, db
from ..models import MOTIVOS_CANCELACION, Cita, Especialidad, Profesional, Servicio, Sucursal
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
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.categoria, Servicio.nombre).all()
    profesionales = Profesional.query.filter_by(activo=True).order_by(Profesional.nombre).all()
    sucursales = Sucursal.query.filter_by(activa=True).order_by(Sucursal.nombre).all()
    usadas = {e.id for p in profesionales for e in p.especialidades}
    especialidades = [e for e in Especialidad.query.order_by(Especialidad.nombre).all() if e.id in usadas]
    pasarelas = ajustes.pasarelas() if ajustes.pagos_activos() else []
    config = {
        "api": request.script_root + "/api/",
        "pedirRut": bool(ajustes.get("pedir_rut")),
        "pagoModo": ajustes.get("pago_modo") if pasarelas else "ninguno",
        "pagoPct": int(ajustes.get("pago_porcentaje")),
        "pasarelas": pasarelas,
        "hoy": ahora().date().isoformat(),
        "diasMaximo": int(ajustes.get("dias_maximo")),
        "sucursales": [{"id": s.id, "nombre": s.nombre, "direccion": s.direccion} for s in sucursales],
        "especialidades": [{"id": e.id, "nombre": e.nombre} for e in especialidades],
        "servicios": [
            {
                "id": s.id,
                "nombre": s.nombre,
                "categoria": s.categoria,
                "descripcion": s.descripcion,
                "duracion": s.duracion,
                "modalidades": s.modalidades,
                "precio": s.precio,
                "tarifas": [
                    {"modalidad": t.modalidad, "especialidad": t.especialidad_id, "profesional": t.profesional_id,
                     "sucursal": t.sucursal_id, "precio": t.precio}
                    for t in s.tarifas
                ],
            }
            for s in servicios
        ],
        "profesionales": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "titulo": p.titulo,
                "servicios": [s.id for s in p.servicios] or None,
                "especialidades": [e.id for e in p.especialidades],
                "sucursales": sorted({h.sucursal_id for h in p.horarios if h.sucursal_id and h.modalidad != "online"}),
                "atiendeSinSucursal": any(h.sucursal_id is None and h.modalidad != "online" for h in p.horarios),
                "modalidades": sorted({m for h in p.horarios for m in (["presencial", "online"] if h.modalidad == "ambas" else [h.modalidad])}),
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
    dias = calcular(
        servicio, profesionales, desde, hasta,
        sucursal_id=request.args.get("sucursal", type=int) or None,
        modalidad=request.args.get("modalidad") or None,
        especialidad_id=request.args.get("especialidad", type=int) or None,
    )
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

    lugar = ""
    if cita.sucursal and not cita.online:
        lugar = cita.sucursal.nombre + (f", {cita.sucursal.direccion}" if cita.sucursal.direccion else "")
    resp = {
        "ok": True,
        "enlace": url_for("publico.cita", token=cita.token),
        "mensaje": ajustes.get("mensaje_confirmacion"),
        "cita": {
            "servicio": cita.servicio.nombre,
            "profesional": cita.profesional.nombre,
            "fecha": fecha_larga(cita.inicio),
            "online": cita.online,
            "lugar": lugar,
            "precio": pesos(cita.precio) if cita.precio else "",
        },
    }

    if cita.estado_pago == "pendiente":
        pasarelas = ajustes.pasarelas()
        pasarela = datos.get("pasarela") if datos.get("pasarela") in pasarelas else (pasarelas[0] if pasarelas else "")
        if pasarela:
            resp["pago_url"] = url_for("publico.pagar", token=cita.token, pasarela=pasarela)
            resp["pago_monto"] = pesos(cita.monto)
            if cita.expira:
                return jsonify(resp)  # Los avisos salen cuando se confirme el pago.
        else:
            cita.estado_pago, cita.monto = "por_cobrar", 0
            db.session.commit()

    correos.nueva_cita(cita)
    resp["cita"]["sesion"] = cita.enlace_sesion
    return jsonify(resp)


# ---------- Pagar ----------

@bp.route("/cita/<token>/pagar", methods=["GET", "POST"])
@csrf.exempt
def pagar(token):
    c = Cita.query.filter_by(token=token).first_or_404()
    aqui = url_for("publico.cita", token=token)
    pasarela = request.values.get("pasarela", "")
    if pasarela not in ajustes.pasarelas():
        return redirect(f"{aqui}?r=pago_no_disponible")
    if c.estado == "cancelada" or c.saldo <= 0 or (c.expira and c.expira < ahora()):
        return redirect(f"{aqui}?r=pago_no_disponible")
    monto = c.monto if c.monto > 0 else c.saldo
    try:
        if pasarela == "mercadopago":
            return redirect(pagos.url_de_pago(c, monto if c.monto <= 0 else None))
        url, tk = webpay.iniciar(c, monto)
    except (pagos.PagoError, webpay.WebpayError) as e:
        current_app.logger.warning("No se pudo iniciar el pago de la cita %s: %s", c.id, e)
        return redirect(f"{aqui}?r=pago_no_disponible")
    return render_template("publico/webpay_ir.html", url=url, token_ws=tk, monto=monto, color=ajustes.get("color"),
                           pruebas=webpay.en_pruebas(), incrustado=False)


@bp.route("/pago/webpay", methods=["GET", "POST"])
@csrf.exempt
def webpay_volver():
    token = request.values.get("token_ws")
    if token:
        try:
            cita, aprobado = webpay.confirmar(token)
        except webpay.WebpayError:
            cita, aprobado = None, False
        if cita is None:
            abort(404)
        return redirect(url_for("publico.cita", token=cita.token, r="pagado" if aprobado else "pago_fallido"))
    # El paciente anuló o se le acabó el tiempo en Webpay.
    cita = webpay.anular_intento(request.values.get("TBK_ORDEN_COMPRA", ""))
    if cita is None:
        return redirect(url_for("publico.reservar_pagina"))
    return redirect(url_for("publico.cita", token=cita.token, r="pago_fallido"))


MENSAJES = {
    "pagado": ("ok", "Recibimos tu pago. Te enviamos el detalle por correo."),
    "pago_en_revision": ("", "Tu pago está en revisión. Cuando se apruebe te llegará un correo."),
    "pago_fallido": ("error", "El pago no se completó. Puedes intentarlo de nuevo."),
    "pago_no_disponible": ("error", "No se pudo abrir el pago. Si el plazo terminó, reserva una hora nueva."),
    "cancelada": ("ok", "Cancelamos tu hora. Gracias por avisar."),
    "no_cancelable": ("error", "Esta hora ya no se puede cancelar en línea. Escríbenos."),
}


@bp.route("/cita/<token>", methods=["GET", "POST"])
@csrf.exempt
def cita(token):
    c = Cita.query.filter_by(token=token).first_or_404()
    aqui = url_for("publico.cita", token=token)

    # Vuelta desde Mercado Pago.
    if "payment_id" in request.args or "collection_status" in request.args:
        estado = request.args.get("collection_status") or request.args.get("status") or ""
        resultado = "pago_fallido"
        if estado == "approved" and request.args.get("payment_id"):
            try:
                pagada = pagos.verificar(request.args["payment_id"], c)
                resultado = "pagado" if pagada and pagada.pagado > 0 else "pago_en_revision"
            except pagos.PagoError:
                resultado = "pago_en_revision"
        elif estado in ("pending", "in_process"):
            resultado = "pago_en_revision"
        return redirect(f"{aqui}?r={resultado}")

    if request.method == "POST":
        if request.form.get("accion") == "cancelar":
            if cancelable(c):
                c.cancelar("paciente", request.form.get("motivo", ""))
                db.session.commit()
                sesiones.cancelar(c)
                correos.cancelada_por_paciente(c)
                return redirect(f"{aqui}?r=cancelada")
            return redirect(f"{aqui}?r=no_cancelable")
        abort(400)

    pasarelas = ajustes.pasarelas()
    puede_pagar = c.estado != "cancelada" and c.saldo > 0 and bool(pasarelas) and (
        c.estado_pago == "pendiente" or ajustes.get("pago_modo") != "ninguno")
    return render_template(
        "publico/cita.html",
        c=c,
        mensaje=MENSAJES.get(request.args.get("r", "")),
        puede_pagar=puede_pagar,
        a_pagar=c.monto if c.monto > 0 else c.saldo,
        pasarelas=pasarelas,
        puede_cancelar=cancelable(c),
        motivos=MOTIVOS_CANCELACION,
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


# ---------- Tareas programadas ----------

@bp.route("/tareas/recordatorios", methods=["GET", "POST"])
@csrf.exempt
def tarea_recordatorios():
    """Llamar cada hora (Render Cron Job o GitHub Actions) con ?clave=CLAVE_TAREAS.
    Envía el recordatorio de las citas que empiezan en las próximas 24 horas."""
    clave = current_app.config["CLAVE_TAREAS"]
    if not clave or not hmac.compare_digest(request.values.get("clave", ""), clave):
        abort(403)
    liberar_horas_sin_pagar()
    momento = ahora()
    citas = Cita.query.filter(
        Cita.inicio > momento, Cita.inicio <= momento + timedelta(hours=24),
        Cita.estado.in_(["confirmada", "pendiente"]), Cita.recordatorio_enviado.is_(None),
        Cita.creada < momento - timedelta(hours=1),  # recién reservada: ya tiene su confirmación
    ).all()
    enviados = 0
    for c in citas:
        if c.espera_pago:
            continue
        correos.recordatorio(c)
        correos.marcar_recordatorio(c)
        enviados += 1
    db.session.commit()
    return jsonify(enviados=enviados)
