"""Módulo Cobranza: lo que se debe, lo cobrado y el resumen por profesional."""
import csv
import io
from datetime import datetime, time, timedelta

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .. import cobros, correos
from ..extensions import db
from ..models import MEDIOS_PAGO, Cita, Pago
from ..permisos import requiere
from ..tiempo import ahora
from . import bp
from .comun import fecha, profesionales_visibles, sucursales


def _periodo():
    hoy = ahora().date()
    desde = fecha(request.args.get("desde"), hoy.replace(day=1))
    hasta = max(desde, fecha(request.args.get("hasta"), hoy))
    return desde, hasta


def _filtros(q, modelo):
    prof = request.args.get("profesional", type=int) if current_user.ve_todo else current_user.profesional_id
    if prof:
        q = q.filter(modelo.profesional_id == prof)
    return q, prof


@bp.get("/cobranza")
@requiere("cobranza")
def cobranza():
    desde, hasta = _periodo()
    hoy = ahora().date()
    suc = request.args.get("sucursal", type=int)

    # Deudas: citas ya ocurridas (o atendidas) con saldo, de cualquier fecha.
    q, prof = _filtros(Cita.query.filter(Cita.estado.notin_(["cancelada", "no_asistio"]), Cita.precio > 0,
                                         Cita.estado_pago.notin_(["pagado", "sin_costo"]),
                                         Cita.inicio < datetime.combine(hoy + timedelta(days=1), time())), Cita)
    if suc:
        q = q.filter(Cita.sucursal_id == suc)
    deudas = [c for c in q.order_by(Cita.inicio).all() if cobros.es_deuda(c, hoy)]

    # Pagos del periodo.
    qp, _ = _filtros(Pago.query.filter(Pago.fecha >= desde, Pago.fecha <= hasta), Pago)
    if suc:
        qp = qp.join(Cita, Pago.cita_id == Cita.id).filter(Cita.sucursal_id == suc)
    pagos = qp.order_by(Pago.fecha.desc(), Pago.id.desc()).all()
    por_medio = {}
    for p in pagos:
        por_medio[p.medio] = por_medio.get(p.medio, 0) + p.monto

    # Por profesional: atendido (valor de las citas) y cobrado en el periodo.
    qc, _ = _filtros(Cita.query.filter(Cita.inicio >= datetime.combine(desde, time()),
                                       Cita.inicio < datetime.combine(hasta + timedelta(days=1), time()),
                                       Cita.estado.notin_(["cancelada", "no_asistio"])), Cita)
    if suc:
        qc = qc.filter(Cita.sucursal_id == suc)
    por_prof = {}
    for c in qc.all():
        fila = por_prof.setdefault(c.profesional_id, {"nombre": c.profesional.nombre, "citas": 0, "valor": 0, "cobrado": 0})
        fila["citas"] += 1
        fila["valor"] += c.precio
    for p in pagos:
        if p.profesional_id:
            fila = por_prof.setdefault(p.profesional_id, {"nombre": p.profesional.nombre if p.profesional else "—", "citas": 0, "valor": 0, "cobrado": 0})
            fila["cobrado"] += p.monto

    if request.args.get("formato") == "csv":
        salida = io.StringIO()
        w = csv.writer(salida, delimiter=";")
        w.writerow(["Fecha", "Paciente", "RUT", "Profesional", "Servicio", "Medio", "Monto", "Referencia"])
        for p in pagos:
            c = p.cita
            w.writerow([p.fecha.isoformat(), c.nombre if c else "", c.rut if c else "", p.profesional.nombre if p.profesional else "",
                        c.servicio.nombre if c else "", MEDIOS_PAGO.get(p.medio, p.medio), p.monto, p.referencia])
        return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=pagos-{desde}-{hasta}.csv"})

    return render_template(
        "panel/cobranza.html", desde=desde, hasta=hasta, prof=prof, suc=suc, deudas=deudas,
        total_deuda=sum(c.saldo for c in deudas), pagos=pagos, total_cobrado=sum(p.monto for p in pagos),
        por_medio=sorted(por_medio.items(), key=lambda x: -x[1]),
        por_prof=sorted(por_prof.values(), key=lambda f: -f["cobrado"]),
        visibles=profesionales_visibles(), sucursales=sucursales(),
    )


@bp.post("/cobranza/recordar")
@requiere("cobranza")
def cobranza_recordar():
    """Envía el recordatorio de saldo a las citas marcadas."""
    enviados = 0
    for cid in request.form.getlist("cita"):
        c = db.session.get(Cita, int(cid)) if cid.isdigit() else None
        if c and c.saldo > 0 and (current_user.ve_todo or c.profesional_id == current_user.profesional_id):
            correos.cobro(c, correos.url_absoluta("publico.cita", token=c.token))
            enviados += 1
    flash(f"Recordatorio enviado a {enviados} {'paciente' if enviados == 1 else 'pacientes'}.", "ok")
    return redirect(request.referrer or url_for("panel.cobranza"))


@bp.post("/cobranza/pago/<int:pago_id>/borrar")
@requiere("cobranza")
def cobranza_borrar_pago(pago_id):
    p = db.session.get(Pago, pago_id)
    if p and (current_user.ve_todo or p.profesional_id == current_user.profesional_id):
        cobros.borrar(p)
        flash("Pago borrado.", "ok")
    current_app.logger.info("Pago %s borrado por %s", pago_id, current_user.email)
    return redirect(request.referrer or url_for("panel.cobranza"))
