"""Módulo Agendar: buscar horas libres y agendar a un paciente (existente o
nuevo). También sirve para sobrecupos fuera de horario."""
from datetime import timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from .. import correos, sesiones
from ..disponibilidad import calcular, modalidad_de
from ..extensions import db
from ..models import Especialidad, Paciente, Servicio
from ..permisos import requiere
from ..precios import precio_para
from ..reservas import ReservaError, reservar
from ..tiempo import ahora
from . import bp
from .comun import buscar_pacientes, fecha, pacientes_visibles, profesionales_visibles, sucursales


@bp.get("/agendar")
@requiere("agendar")
def agendar():
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.categoria, Servicio.nombre).all()
    visibles = profesionales_visibles(solo_activos=True)
    servicio = next((s for s in servicios if s.id == request.args.get("servicio", type=int)), servicios[0] if servicios else None)
    prof_id = request.args.get("profesional", type=int) or (None if current_user.ve_todo else current_user.profesional_id)
    modalidad = request.args.get("modalidad") or None
    sucursal = request.args.get("sucursal", type=int) or None
    especialidad = request.args.get("especialidad", type=int) or None
    desde = max(fecha(request.args.get("desde"), ahora().date()), ahora().date())
    dias_ver = 7

    libres = {}
    if servicio:
        profs = [p for p in visibles if not prof_id or p.id == prof_id]
        libres = calcular(servicio, profs, desde, desde + timedelta(days=dias_ver - 1), sucursal_id=sucursal,
                          equipo=True, modalidad=modalidad, especialidad_id=especialidad)
    nombres = {p.id: p.nombre for p in visibles}
    return render_template(
        "panel/agendar.html",
        servicios=servicios, servicio=servicio, visibles=visibles, prof_id=prof_id, modalidad=modalidad,
        sucursal=sucursal, sucursales=sucursales(), especialidad=especialidad,
        especialidades=Especialidad.query.order_by(Especialidad.nombre).all(),
        desde=desde, dias=[desde + timedelta(days=i) for i in range(dias_ver)], libres=libres, nombres=nombres,
        paciente=request.args.get("paciente", type=int) or "",
        necesita_modalidad=servicio is not None and servicio.modalidad == "ambas" and not modalidad,
    )


@bp.route("/agendar/confirmar", methods=["GET", "POST"])
@requiere("agendar")
def agendar_confirmar():
    servicios = Servicio.query.order_by(Servicio.activo.desc(), Servicio.categoria, Servicio.nombre).all()
    visibles = profesionales_visibles(solo_activos=True)
    if request.method == "POST":
        d = request.form.to_dict()
    else:
        d = {k: request.args.get(k, "") for k in ("servicio_id", "profesional_id", "fecha", "hora", "modalidad",
                                                  "sucursal_id", "especialidad_id", "paciente_id")}
        d.setdefault("estado", "confirmada")
        d["fecha"] = d["fecha"] or ahora().date().isoformat()
        d["avisar"] = "1"
        if not d["profesional_id"] and not current_user.ve_todo:
            d["profesional_id"] = str(current_user.profesional_id or "")
    if not current_user.ve_todo:
        d["profesional_id"] = str(current_user.profesional_id or "")

    paciente = db.session.get(Paciente, int(d["paciente_id"])) if str(d.get("paciente_id") or "").isdigit() else None

    if request.method == "POST":
        if not d.get("paciente_id"):
            d.pop("paciente_id", None)
        try:
            c = reservar(d, desde_panel=True)
        except ReservaError as e:
            flash(str(e), "error")
        else:
            if d.get("avisar"):
                correos.nueva_cita(c, avisar_equipo=False)
            else:
                sesiones.asegurar(c)
            flash("Cita agendada.", "ok")
            return redirect(url_for("panel.cita", cita_id=c.id))

    servicio = next((s for s in servicios if str(s.id) == str(d.get("servicio_id"))), None)
    precio_sugerido = ""
    if servicio and str(d.get("profesional_id") or "").isdigit():
        precio_sugerido = precio_para(servicio, modalidad_de(servicio, d.get("modalidad")), int(d["profesional_id"]),
                                      int(d["sucursal_id"]) if str(d.get("sucursal_id") or "").isdigit() else None,
                                      int(d["especialidad_id"]) if str(d.get("especialidad_id") or "").isdigit() else None)
    return render_template("panel/agendar_confirmar.html", servicios=servicios, visibles=visibles, d=d,
                           paciente=paciente, sucursales=sucursales(), precio_sugerido=precio_sugerido,
                           especialidades=Especialidad.query.order_by(Especialidad.nombre).all())


@bp.get("/pacientes/buscar")
@requiere("agendar")
def buscar_paciente():
    texto = request.args.get("q", "").strip()
    if len(texto) < 2:
        return jsonify([])
    lista = buscar_pacientes(pacientes_visibles(), texto).order_by(Paciente.nombre).limit(12).all()
    return jsonify([{"id": p.id, "nombre": p.nombre, "rut": p.rut, "email": p.email, "telefono": p.telefono} for p in lista])
