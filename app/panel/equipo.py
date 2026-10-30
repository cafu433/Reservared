"""Módulo Profesionales y permisos: perfiles de profesionales (datos,
especialidades, servicios, horario por tramo con modalidad y sucursal) y las
cuentas del equipo con sus permisos."""
import secrets

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .. import correos
from ..extensions import db
from ..models import DIAS_SEMANA, MODALIDADES_TRAMO, Cita, Especialidad, Horario, Profesional, Servicio, Usuario
from ..permisos import PERFILES, PERMISOS, requiere
from . import bp
from .comun import enlace_clave, hora, sucursales

TRAMOS_POR_DIA = 3


@bp.route("/profesionales", methods=["GET", "POST"])
@requiere("equipo")
def profesionales():
    if request.method == "POST":
        if request.form.get("accion") == "especialidad":
            nombre = request.form.get("nombre", "").strip()[:120]
            if nombre and not Especialidad.query.filter(func.lower(Especialidad.nombre) == nombre.lower()).first():
                db.session.add(Especialidad(nombre=nombre))
                db.session.commit()
                flash(f"Especialidad «{nombre}» agregada.", "ok")
        elif request.form.get("accion") == "borrar_especialidad":
            e = db.session.get(Especialidad, request.form.get("id", type=int) or 0)
            if e:
                db.session.delete(e)
                db.session.commit()
                flash("Especialidad quitada.", "ok")
        return redirect(url_for("panel.profesionales"))
    lista = Profesional.query.order_by(Profesional.activo.desc(), Profesional.nombre).all()
    return render_template("panel/profesionales.html", lista=lista,
                           especialidades=Especialidad.query.order_by(Especialidad.nombre).all())


def _tramos_form():
    tramos = {}
    for dia in range(7):
        for i in range(TRAMOS_POR_DIA):
            a, z = request.form.get(f"h-{dia}-{i}-ini", ""), request.form.get(f"h-{dia}-{i}-fin", "")
            if a or z:
                tramos.setdefault(dia, []).append({"ini": a, "fin": z, "mod": request.form.get(f"h-{dia}-{i}-mod", "ambas"),
                                                   "suc": request.form.get(f"h-{dia}-{i}-suc", type=int)})
    return tramos


@bp.route("/profesionales/nuevo", methods=["GET", "POST"])
@bp.route("/profesionales/<int:prof_id>", methods=["GET", "POST"])
@login_required
def profesional(prof_id=None):
    admin = current_user.puede("equipo")
    propio = prof_id is not None and prof_id == current_user.profesional_id
    if not admin and not propio:
        abort(403)
    p = db.session.get(Profesional, prof_id) if prof_id else Profesional(activo=True)
    if prof_id and not p:
        abort(404)
    todos_servicios = Servicio.query.order_by(Servicio.categoria, Servicio.nombre).all()
    todas_esp = Especialidad.query.order_by(Especialidad.nombre).all()

    def pintar(tramos):
        return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, especialidades=todas_esp,
                               tramos=tramos, admin=admin, sucursales=sucursales(), tramos_por_dia=TRAMOS_POR_DIA)

    if request.method == "POST":
        if request.form.get("accion") == "borrar" and admin and p.id:
            if Cita.query.filter_by(profesional_id=p.id).first():
                p.activo = False
                if p.usuario:
                    p.usuario.activo = False
                flash("Tiene citas registradas, así que no se borró: quedó inactivo y sin acceso.", "aviso")
            else:
                if p.usuario:
                    db.session.delete(p.usuario)
                db.session.delete(p)
                flash("Profesional borrado.", "ok")
            db.session.commit()
            return redirect(url_for("panel.profesionales"))

        tramos = []
        for dia, lista in _tramos_form().items():
            for t in lista:
                ta, tz = hora(t["ini"]), hora(t["fin"])
                if not ta or not tz or tz <= ta:
                    flash(f"Revisa el horario del {DIAS_SEMANA[dia].lower()}: cada tramo tiene que terminar después de empezar.", "error")
                    return pintar(_tramos_form())
                mod = t["mod"] if t["mod"] in MODALIDADES_TRAMO else "ambas"
                tramos.append((dia, ta, tz, mod, t["suc"] if mod != "online" else None))

        p.enlace_sala = request.form.get("enlace_sala", "").strip()[:500]
        if admin:
            p.nombre = request.form.get("nombre", "").strip()[:190]
            p.titulo = request.form.get("titulo", "").strip()[:190]
            p.email = request.form.get("email", "").strip().lower()[:190]
            p.activo = bool(request.form.get("activo"))
            elegidos = {int(x) for x in request.form.getlist("servicios") if x.isdigit()}
            p.servicios = [s for s in todos_servicios if s.id in elegidos]
            esp = {int(x) for x in request.form.getlist("especialidades") if x.isdigit()}
            p.especialidades = [e for e in todas_esp if e.id in esp]
            if not p.nombre:
                flash("Falta el nombre.", "error")
                return pintar(_tramos_form())

        db.session.add(p)
        db.session.flush()
        Horario.query.filter_by(profesional_id=p.id).delete()
        for dia, ta, tz, mod, suc in tramos:
            db.session.add(Horario(profesional_id=p.id, dia=dia, inicio=ta, fin=tz, modalidad=mod, sucursal_id=suc))

        nuevo_usuario = None
        if admin and request.form.get("acceso") and not p.usuario:
            if not p.email:
                db.session.rollback()
                flash("Para darle acceso al panel, escribe su correo.", "error")
                return pintar(_tramos_form())
            if Usuario.query.filter(func.lower(Usuario.email) == p.email).first():
                db.session.rollback()
                flash("Ese correo ya tiene una cuenta. Vincúlala desde Cuentas y permisos.", "error")
                return pintar(_tramos_form())
            nuevo_usuario = Usuario(email=p.email, nombre=p.nombre, rol="profesional", profesional=p)
            nuevo_usuario.poner_permisos(PERFILES["profesional"][1])
            nuevo_usuario.poner_clave(secrets.token_urlsafe(16))
            db.session.add(nuevo_usuario)
        elif admin and p.usuario:
            p.usuario.activo = bool(request.form.get("acceso")) and p.activo
            p.usuario.nombre = p.nombre

        db.session.commit()
        if nuevo_usuario:
            correos.acceso_nuevo(nuevo_usuario, enlace_clave(nuevo_usuario))
            flash(f"Le enviamos a {p.email} un enlace para elegir su contraseña. Sus permisos se ajustan en Cuentas y permisos.", "ok")
        flash("Guardado.", "ok")
        return redirect(url_for("panel.profesional", prof_id=p.id))

    tramos = {}
    for h in p.horarios if p.id else []:
        tramos.setdefault(h.dia, []).append({"ini": h.inicio.strftime("%H:%M"), "fin": h.fin.strftime("%H:%M"),
                                             "mod": h.modalidad, "suc": h.sucursal_id})
    if not p.id:
        tramos = {d: [{"ini": "09:00", "fin": "13:00", "mod": "ambas", "suc": None},
                      {"ini": "15:00", "fin": "19:00", "mod": "ambas", "suc": None}] for d in range(5)}
    return pintar(tramos)


@bp.get("/mi-horario")
@login_required
def mi_horario():
    if not current_user.profesional_id:
        return redirect(url_for("panel.profesionales"))
    return redirect(url_for("panel.profesional", prof_id=current_user.profesional_id))


# ---------- Cuentas y permisos ----------

@bp.get("/cuentas")
@requiere("equipo")
def cuentas():
    lista = Usuario.query.order_by(Usuario.activo.desc(), Usuario.nombre).all()
    return render_template("panel/cuentas.html", lista=lista, PERFILES=PERFILES)


@bp.route("/cuentas/nueva", methods=["GET", "POST"])
@bp.route("/cuentas/<int:usuario_id>", methods=["GET", "POST"])
@requiere("equipo")
def cuenta_editar(usuario_id=None):
    u = db.session.get(Usuario, usuario_id) if usuario_id else Usuario(rol="recepcion", activo=True)
    if usuario_id and not u:
        abort(404)
    if u.id and u.es_admin and not current_user.es_admin:
        abort(403)
    profesionales = Profesional.query.order_by(Profesional.nombre).all()

    if request.method == "POST":
        if request.form.get("accion") == "borrar" and u.id:
            if u.id == current_user.id:
                flash("No puedes borrar tu propia cuenta.", "error")
            else:
                db.session.delete(u)
                db.session.commit()
                flash("Cuenta borrada.", "ok")
                return redirect(url_for("panel.cuentas"))
        else:
            email = request.form.get("email", "").strip().lower()
            nombre = request.form.get("nombre", "").strip()
            rol = request.form.get("rol") if request.form.get("rol") in PERFILES else "personalizado"
            if rol == "admin" and not current_user.es_admin:
                abort(403)
            otro = Usuario.query.filter(func.lower(Usuario.email) == email, Usuario.id != (u.id or 0)).first()
            prof_id = request.form.get("profesional_id", type=int) or None
            ocupado = prof_id and Usuario.query.filter(Usuario.profesional_id == prof_id, Usuario.id != (u.id or 0)).first()
            if not email or "@" not in email or not nombre:
                flash("Escribe nombre y correo.", "error")
            elif otro:
                flash("Ese correo ya tiene cuenta.", "error")
            elif ocupado:
                flash("Ese profesional ya tiene otra cuenta.", "error")
            elif u.id == current_user.id and u.es_admin and rol != "admin":
                flash("No puedes quitarte la administración a ti misma(o). Pídeselo a otra cuenta de administración.", "error")
            else:
                nueva = u.id is None
                u.email, u.nombre, u.rol, u.profesional_id = email, nombre, rol, prof_id
                permisos = [k for k in request.form.getlist("permisos") if k in PERMISOS]
                # Nadie da permisos que no tiene (salvo la administración).
                if not current_user.es_admin:
                    permisos = [k for k in permisos if current_user.puede(k)]
                u.poner_permisos(permisos)
                u.activo = bool(request.form.get("activo")) or u.id == current_user.id
                if nueva:
                    u.poner_clave(secrets.token_urlsafe(16))
                    db.session.add(u)
                db.session.commit()
                if nueva:
                    correos.acceso_nuevo(u, enlace_clave(u))
                    flash(f"Cuenta creada. Le enviamos a {email} un enlace para elegir su contraseña.", "ok")
                else:
                    flash("Cuenta guardada.", "ok")
                return redirect(url_for("panel.cuentas"))

    return render_template("panel/cuenta_editar.html", u=u, profesionales=profesionales, PERFILES=PERFILES,
                           permisos_actuales=u.lista_permisos if u.id else set(PERFILES[u.rol][1]))
