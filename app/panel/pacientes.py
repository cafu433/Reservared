"""Módulo Pacientes: listado y ficha (datos, historial, pagos) con la ficha
clínica aparte, sólo para quien tiene ese permiso."""
from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ..extensions import db
from ..models import PREVISIONES, Cita, Evolucion, Paciente
from ..permisos import requiere
from ..reservas import formatear_rut, rut_valido
from ..tiempo import ahora
from . import bp
from .comun import buscar_pacientes, fecha, pacientes_visibles, paciente_visible


@bp.get("/pacientes")
@requiere("pacientes")
def pacientes():
    texto = request.args.get("q", "").strip()
    q = pacientes_visibles()
    if texto:
        q = buscar_pacientes(q, texto)
    pagina = max(1, request.args.get("pagina", type=int) or 1)
    lista = q.order_by(Paciente.nombre).offset((pagina - 1) * 50).limit(51).all()
    ids = [p.id for p in lista[:50]]
    resumen = {}
    if ids:
        filas = db.session.query(Cita.paciente_id, func.count(Cita.id), func.max(Cita.inicio)).filter(
            Cita.paciente_id.in_(ids), Cita.estado != "cancelada").group_by(Cita.paciente_id).all()
        resumen = {pid: (n, ultima) for pid, n, ultima in filas}
    return render_template("panel/pacientes.html", lista=lista[:50], hay_mas=len(lista) > 50, num_pagina=pagina,
                           texto=texto, resumen=resumen)


def _datos_desde_form(p):
    f = request.form
    p.nombre = f.get("nombre", "").strip()[:190]
    rut = f.get("rut", "").strip()
    if rut and not rut_valido(rut):
        return "El RUT no es válido."
    p.rut = formatear_rut(rut) if rut else ""
    p.email = f.get("email", "").strip().lower()[:190]
    p.telefono = f.get("telefono", "").strip()[:40]
    p.fecha_nacimiento = fecha(f.get("fecha_nacimiento"), None)
    p.prevision = f.get("prevision", "") if f.get("prevision", "") in PREVISIONES else ""
    p.direccion = f.get("direccion", "").strip()[:255]
    p.contacto_emergencia = f.get("contacto_emergencia", "").strip()[:255]
    p.notas = f.get("notas", "").strip()
    if not p.nombre:
        return "Falta el nombre."
    if p.rut:
        otro = Paciente.query.filter(Paciente.rut == p.rut, Paciente.id != (p.id or 0)).first()
        if otro:
            return f"Ese RUT ya es de {otro.nombre}."
    return None


@bp.route("/pacientes/nuevo", methods=["GET", "POST"])
@requiere("pacientes")
def paciente_nuevo():
    p = Paciente()
    if request.method == "POST":
        error = _datos_desde_form(p)
        if error:
            flash(error, "error")
        else:
            p.creado = ahora()
            db.session.add(p)
            db.session.commit()
            flash("Paciente creado.", "ok")
            return redirect(url_for("panel.paciente", paciente_id=p.id))
    return render_template("panel/paciente_nuevo.html", p=p)


@bp.route("/pacientes/<int:paciente_id>", methods=["GET", "POST"])
@requiere("pacientes")
def paciente(paciente_id):
    p = paciente_visible(paciente_id)
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "datos":
            error = _datos_desde_form(p)
            if error:
                db.session.rollback()
                flash(error, "error")
            else:
                db.session.commit()
                flash("Datos guardados.", "ok")
        elif accion in ("clinica", "evolucion", "editar_evolucion"):
            if not current_user.puede("ficha_clinica"):
                abort(403)
            if accion == "clinica":
                p.motivo_consulta = request.form.get("motivo_consulta", "").strip()
                p.antecedentes = request.form.get("antecedentes", "").strip()
                flash("Ficha clínica guardada.", "ok")
            elif accion == "evolucion":
                texto = request.form.get("texto", "").strip()
                if texto:
                    db.session.add(Evolucion(paciente_id=p.id, autor_id=current_user.id, fecha=ahora(), texto=texto,
                                             profesional_id=current_user.profesional_id))
                    flash("Nota de evolución agregada.", "ok")
            else:
                ev = db.session.get(Evolucion, request.form.get("evolucion_id", type=int) or 0)
                if not ev or ev.paciente_id != p.id or ev.autor_id != current_user.id:
                    abort(403)
                ev.texto = request.form.get("texto", "").strip() or ev.texto
                ev.editada = ahora()
                flash("Nota actualizada.", "ok")
            db.session.commit()
        return redirect(url_for("panel.paciente", paciente_id=p.id) + ("#clinica" if accion != "datos" else ""))

    citas = p.citas.all()
    if not current_user.ve_todo:
        citas = [c for c in citas if c.profesional_id == current_user.profesional_id]
    pagos = sorted([pg for c in citas for pg in c.pagos], key=lambda x: x.fecha, reverse=True)
    momento = ahora()
    proximas = sorted([c for c in citas if c.inicio >= momento and c.estado != "cancelada"], key=lambda c: c.inicio)
    pasadas = [c for c in citas if c not in proximas]
    resumen = {
        "atendidas": sum(1 for c in citas if c.estado == "asistio"),
        "inasistencias": sum(1 for c in citas if c.estado == "no_asistio"),
        "canceladas": sum(1 for c in citas if c.estado == "cancelada"),
        "saldo": sum(c.saldo for c in citas if c.estado not in ("cancelada",) and c.inicio <= momento),
        "pagado": sum(pg.monto for pg in pagos),
    }
    evoluciones = p.evoluciones.all() if current_user.puede("ficha_clinica") else []
    return render_template("panel/paciente.html", p=p, proximas=proximas, pasadas=pasadas, pagos=pagos,
                           resumen=resumen, evoluciones=evoluciones)
