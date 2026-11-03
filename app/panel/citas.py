"""Citas: listado, ficha de la cita y sus acciones (estado, reagendar,
copiar, cancelar, pagos, sesión online, WhatsApp, nota de evolución)."""
from datetime import datetime, time, timedelta

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .. import cobros, correos, sesiones, whatsapp
from ..extensions import db
from ..models import ESTADOS, Cita, Evolucion, Pago
from ..permisos import requiere
from ..reservas import ReservaError, copiar, reagendar
from ..tiempo import ahora, pesos
from . import bp
from .comun import cita_visible, entero, fecha, filtro_citas_propias, profesionales_visibles, sucursales


@bp.get("/citas")
@requiere("agenda")
def citas():
    hoy = ahora().date()
    desde = fecha(request.args.get("desde"), hoy)
    hasta = max(desde, fecha(request.args.get("hasta"), hoy + timedelta(days=6)))
    q = filtro_citas_propias(Cita.query.filter(Cita.inicio >= datetime.combine(desde, time()),
                                               Cita.inicio < datetime.combine(hasta + timedelta(days=1), time())))
    prof = request.args.get("profesional", type=int) if current_user.ve_todo else None
    if prof:
        q = q.filter(Cita.profesional_id == prof)
    suc = request.args.get("sucursal", type=int)
    if suc:
        q = q.filter(Cita.sucursal_id == suc)
    estado = request.args.get("estado", "")
    if estado in ESTADOS:
        q = q.filter(Cita.estado == estado)
    texto = request.args.get("q", "").strip()
    if texto:
        like = f"%{texto}%"
        q = q.filter(or_(Cita.nombre.ilike(like), Cita.email.ilike(like), Cita.rut.ilike(like), Cita.telefono.ilike(like)))
    lista = q.order_by(Cita.inicio).all()
    por_dia = {}
    for c in lista:
        por_dia.setdefault(c.inicio.date(), []).append(c)
    return render_template("panel/citas.html", por_dia=por_dia, total=len(lista), desde=desde, hasta=hasta, prof=prof,
                           suc=suc, estado=estado, texto=texto, visibles=profesionales_visibles(), sucursales=sucursales())


def _puede_editar():
    if not current_user.puede("agendar"):
        abort(403)


@bp.route("/citas/<int:cita_id>", methods=["GET", "POST"])
@login_required
def cita(cita_id):
    if not (current_user.puede("agenda") or current_user.puede("agendar") or current_user.puede("cobranza")):
        abort(403)
    c = cita_visible(cita_id)
    if request.method == "POST":
        accion = request.form.get("accion")
        destino = url_for("panel.cita", cita_id=c.id)

        if accion == "estado":
            _puede_editar()
            nuevo = request.form.get("estado")
            if nuevo in ESTADOS and nuevo != c.estado:
                if nuevo == "cancelada":
                    c.cancelar("equipo", request.form.get("motivo", ""))
                else:
                    c.estado = nuevo
                    c.expira = None
                    c.cancelada_en, c.cancelada_por = None, ""
                db.session.commit()
                if nuevo == "cancelada":
                    sesiones.cancelar(c)
                    if request.form.get("avisar"):
                        correos.cancelada_por_equipo(c)
                else:
                    sesiones.asegurar(c)
                    if request.form.get("avisar") and nuevo == "confirmada":
                        correos.confirmada(c)
                    correos.enlace_si_falta(c)
                flash(f"Estado: {ESTADOS[nuevo]}.", "ok")

        elif accion == "reagendar":
            _puede_editar()
            try:
                reagendar(c, request.form.get("fecha"), request.form.get("hora"), request.form.get("profesional_id"))
            except ReservaError as e:
                flash(str(e), "error")
            else:
                if request.form.get("avisar"):
                    correos.reagendada(c)
                else:
                    sesiones.cancelar(c)
                    sesiones.asegurar(c)
                flash("Cita reagendada.", "ok")

        elif accion == "copiar":
            _puede_editar()
            try:
                creadas, saltadas = copiar(c, request.form.get("fecha"), request.form.get("hora"),
                                           request.form.get("profesional_id"), request.form.get("semanas", 1))
            except ReservaError as e:
                flash(str(e), "error")
            else:
                for n in creadas:
                    if request.form.get("avisar"):
                        correos.nueva_cita(n, avisar_equipo=False)
                    else:
                        sesiones.asegurar(n)
                texto = f"Se {'creó' if len(creadas) == 1 else 'crearon'} {len(creadas)} {'cita' if len(creadas) == 1 else 'citas'}."
                if saltadas:
                    texto += " No se crearon (horario ocupado): " + ", ".join(f"{d:%d-%m %H:%M}" for d in saltadas) + "."
                flash(texto, "aviso" if saltadas else "ok")
                if len(creadas) == 1:
                    destino = url_for("panel.cita", cita_id=creadas[0].id)

        elif accion == "pago":
            if not current_user.puede("cobranza"):
                abort(403)
            try:
                cobros.registrar(c, entero(request.form.get("monto")), request.form.get("medio"),
                                 fecha(request.form.get("fecha_pago"), ahora().date()), request.form.get("referencia", ""),
                                 request.form.get("nota", ""), current_user.id)
                sesiones.asegurar(c)
                correos.enlace_si_falta(c)
                flash("Pago registrado.", "ok")
            except cobros.CobroError as e:
                flash(str(e), "error")

        elif accion == "borrar_pago":
            if not current_user.puede("cobranza"):
                abort(403)
            p = db.session.get(Pago, request.form.get("pago_id", type=int) or 0)
            if p and p.cita_id == c.id:
                cobros.borrar(p)
                flash("Pago borrado.", "ok")

        elif accion == "precio":
            if not current_user.puede("cobranza"):
                abort(403)
            nuevo = entero(request.form.get("precio"))
            if nuevo is None or nuevo < 0:
                flash("Escribe el valor en pesos, sin puntos.", "error")
            else:
                c.precio = nuevo
                cobros.recalcular(c)
                db.session.commit()
                flash("Valor actualizado.", "ok")

        elif accion == "cobrar":
            if not current_user.puede("cobranza"):
                abort(403)
            correos.cobro(c, correos.url_absoluta("publico.cita", token=c.token) if c.saldo else "")
            flash("Le enviamos al paciente el recordatorio de pago.", "ok")

        elif accion == "nota":
            _puede_editar()
            c.nota_interna = request.form.get("nota_interna", "")[:5000]
            db.session.commit()
            flash("Nota guardada.", "ok")

        elif accion == "evolucion":
            if not current_user.puede("ficha_clinica"):
                abort(403)
            texto = request.form.get("texto", "").strip()
            if texto and c.paciente_id:
                db.session.add(Evolucion(paciente_id=c.paciente_id, cita_id=c.id, autor_id=current_user.id,
                                         profesional_id=current_user.profesional_id or c.profesional_id,
                                         fecha=ahora(), texto=texto))
                db.session.commit()
                flash("Nota de evolución guardada en la ficha clínica.", "ok")

        elif accion == "enlace":
            _puede_editar()
            c.enlace_sesion = request.form.get("enlace_sesion", "").strip()[:500]
            db.session.commit()
            enviado = correos.enlace_si_falta(c)
            flash("Enlace guardado." + (" Se lo enviamos al paciente por correo." if enviado else ""), "ok")

        elif accion == "crear_meet":
            _puede_editar()
            sesiones.cancelar(c)
            c.enlace_sesion = ""
            db.session.commit()
            sesiones.asegurar(c)
            enviado = correos.enlace_si_falta(c)
            if c.enlace_sesion:
                flash("Enlace de sesión creado." + (" Se lo enviamos al paciente por correo." if enviado else ""), "ok")
            else:
                flash("No se pudo crear el Meet. Revisa la conexión con Google.", "error")

        elif accion == "reenviar":
            _puede_editar()
            correos.nueva_cita(c, avisar_equipo=False)
            flash("Confirmación reenviada al paciente (correo y WhatsApp si está activo).", "ok")

        elif accion == "borrar":
            if not current_user.es_admin:
                abort(403)
            sesiones.cancelar(c)
            dia = c.inicio.date().isoformat()
            db.session.delete(c)
            db.session.commit()
            flash("Cita borrada.", "ok")
            return redirect(url_for("panel.agenda", fecha=dia))

        return redirect(destino)

    historial = c.paciente.citas.filter(Cita.id != c.id).limit(15).all() if c.paciente else []
    if not current_user.ve_todo:
        historial = [h for h in historial if h.profesional_id == current_user.profesional_id]
    enlace = correos.url_absoluta("publico.cita", token=c.token)
    negocio = current_app.config["NOMBRE_NEGOCIO"]
    evoluciones = []
    if current_user.puede("ficha_clinica") and c.paciente:
        evoluciones = c.paciente.evoluciones.filter(Evolucion.cita_id == c.id).all()
    return render_template(
        "panel/cita.html", c=c, historial=historial, enlace_paciente=enlace, google=sesiones.google_conectado(),
        visibles=profesionales_visibles(solo_activos=True), evoluciones=evoluciones,
        wa_cita=whatsapp.enlace_manual(c.telefono, whatsapp.texto_cita(c, enlace, negocio)),
        wa_cobro=whatsapp.enlace_manual(c.telefono, whatsapp.texto_cobro(c, enlace, negocio, pesos(c.saldo))) if c.saldo else "",
        hoy=ahora().date(), semana_siguiente=(c.inicio + timedelta(days=7)).date(),
    )


@bp.post("/citas/<int:cita_id>/mover")
@requiere("agendar")
def mover(cita_id):
    """Desde la agenda: arrastrar una cita a otro horario para moverla o copiarla."""
    c = cita_visible(cita_id)
    d = request.get_json(silent=True) or {}
    prof = d.get("profesional_id") or c.profesional_id
    if not current_user.ve_todo:
        prof = current_user.profesional_id
    try:
        if d.get("copiar"):
            creadas, _ = copiar(c, d.get("fecha"), d.get("hora"), prof, 1)
            if not creadas:
                return jsonify(message="Ese horario está ocupado."), 400
            if d.get("avisar"):
                correos.nueva_cita(creadas[0], avisar_equipo=False)
            else:
                sesiones.asegurar(creadas[0])
        else:
            reagendar(c, d.get("fecha"), d.get("hora"), prof)
            if d.get("avisar"):
                correos.reagendada(c)
            else:
                sesiones.cancelar(c)
                sesiones.asegurar(c)
    except ReservaError as e:
        return jsonify(message=str(e)), 400
    return jsonify(ok=True)
