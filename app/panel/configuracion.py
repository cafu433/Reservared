"""Módulo Configuración: servicios y tarifas, sucursales, bloqueos, reglas
de reserva, pagos en línea, WhatsApp y Google."""
import secrets
from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from .. import ajustes, correos, sesiones, webpay, whatsapp
from ..extensions import db
from ..models import Bloqueo, Cita, Especialidad, Profesional, Servicio, Sucursal, Tarifa
from ..permisos import requiere
from ..tiempo import ahora
from . import bp
from .comun import entero, profesionales_visibles, sucursales


# ---------- Servicios y tarifas ----------

@bp.route("/servicios", methods=["GET", "POST"])
@bp.route("/servicios/<int:servicio_id>", methods=["GET", "POST"])
@requiere("configuracion")
def servicios(servicio_id=None):
    s = db.session.get(Servicio, servicio_id) if servicio_id else Servicio(duracion=45, precio=0, modalidad="presencial", activo=True)
    if servicio_id and not s:
        abort(404)
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "borrar" and s.id:
            if Cita.query.filter_by(servicio_id=s.id).first():
                s.activo = False
                flash("Tiene citas registradas, así que no se borró: quedó inactivo y ya no aparece al reservar.", "aviso")
            else:
                db.session.delete(s)
                flash("Servicio borrado.", "ok")
            db.session.commit()
            return redirect(url_for("panel.servicios"))
        if accion == "tarifa" and s.id:
            precio = entero(request.form.get("precio"))
            t = Tarifa(servicio=s, precio=precio or 0,
                       modalidad=request.form.get("modalidad") if request.form.get("modalidad") in ("presencial", "online") else "",
                       especialidad_id=request.form.get("especialidad_id", type=int) or None,
                       profesional_id=request.form.get("profesional_id", type=int) or None,
                       sucursal_id=request.form.get("sucursal_id", type=int) or None)
            if precio is None or precio < 0:
                flash("Escribe el precio en pesos, sin puntos.", "error")
            elif not (t.modalidad or t.especialidad_id or t.profesional_id or t.sucursal_id):
                flash("Elige al menos una condición; si no, cambia el precio base del servicio.", "error")
            else:
                db.session.add(t)
                db.session.commit()
                flash("Precio especial agregado.", "ok")
            return redirect(url_for("panel.servicios", servicio_id=s.id))
        if accion == "borrar_tarifa" and s.id:
            t = db.session.get(Tarifa, request.form.get("tarifa_id", type=int) or 0)
            if t and t.servicio_id == s.id:
                db.session.delete(t)
                db.session.commit()
            return redirect(url_for("panel.servicios", servicio_id=s.id))

        s.nombre = request.form.get("nombre", "").strip()[:190]
        s.categoria = request.form.get("categoria", "").strip()[:120]
        s.descripcion = request.form.get("descripcion", "").strip()
        s.duracion = min(600, max(5, request.form.get("duracion", type=int) or 45))
        s.precio = max(0, entero(request.form.get("precio")) or 0)
        s.modalidad = request.form.get("modalidad") if request.form.get("modalidad") in ("presencial", "online", "ambas") else "presencial"
        s.activo = bool(request.form.get("activo"))
        if not s.nombre:
            flash("El servicio necesita un nombre.", "error")
        else:
            db.session.add(s)
            db.session.commit()
            flash("Servicio guardado.", "ok")
            return redirect(url_for("panel.servicios", servicio_id=s.id))
    lista = Servicio.query.order_by(Servicio.activo.desc(), Servicio.categoria, Servicio.nombre).all()
    categorias = sorted({x.categoria for x in lista if x.categoria})
    return render_template("panel/servicios.html", lista=lista, s=s, categorias=categorias, sucursales=sucursales(),
                           profesionales=Profesional.query.filter_by(activo=True).order_by(Profesional.nombre).all(),
                           especialidades=Especialidad.query.order_by(Especialidad.nombre).all())


# ---------- Sucursales ----------

@bp.route("/sucursales", methods=["GET", "POST"])
@bp.route("/sucursales/<int:sucursal_id>", methods=["GET", "POST"])
@requiere("configuracion")
def sucursales_pagina(sucursal_id=None):
    s = db.session.get(Sucursal, sucursal_id) if sucursal_id else Sucursal(activa=True)
    if sucursal_id and not s:
        abort(404)
    if request.method == "POST":
        s.nombre = request.form.get("nombre", "").strip()[:120]
        s.direccion = request.form.get("direccion", "").strip()[:255]
        s.telefono = request.form.get("telefono", "").strip()[:40]
        s.indicaciones = request.form.get("indicaciones", "").strip()
        s.activa = bool(request.form.get("activa"))
        if not s.nombre:
            flash("La sucursal necesita un nombre.", "error")
        else:
            db.session.add(s)
            db.session.commit()
            flash("Sucursal guardada.", "ok")
            return redirect(url_for("panel.sucursales_pagina"))
    return render_template("panel/sucursales.html", s=s, lista=sucursales(solo_activas=False))


# ---------- Bloqueos ----------

@bp.route("/bloqueos", methods=["GET", "POST"])
@login_required
def bloqueos():
    if not (current_user.puede("agendar") or current_user.profesional_id):
        abort(403)
    if request.method == "POST":
        if request.form.get("accion") == "borrar":
            b = db.session.get(Bloqueo, request.form.get("id", type=int) or 0)
            if b and (current_user.ve_todo or b.profesional_id == current_user.profesional_id):
                db.session.delete(b)
                db.session.commit()
                flash("Bloqueo quitado.", "ok")
            return redirect(url_for("panel.bloqueos"))
        try:
            a = datetime.fromisoformat(f"{request.form['desde_fecha']} {request.form.get('desde_hora') or '00:00'}")
            z = datetime.fromisoformat(f"{request.form['hasta_fecha']} {request.form.get('hasta_hora') or '23:59'}")
        except (KeyError, ValueError):
            a = z = None
        if not a or not z or z <= a:
            flash("El bloqueo tiene que terminar después de empezar.", "error")
        else:
            prof = (request.form.get("profesional_id", type=int) or None) if current_user.ve_todo else current_user.profesional_id
            db.session.add(Bloqueo(profesional_id=prof, inicio=a, fin=z, motivo=request.form.get("motivo", "").strip()[:190]))
            db.session.commit()
            flash("Bloqueo agregado. Esas horas ya no se ofrecen.", "ok")
        return redirect(url_for("panel.bloqueos"))

    q = Bloqueo.query.filter(Bloqueo.fin >= ahora()).order_by(Bloqueo.inicio)
    if not current_user.ve_todo:
        q = q.filter(or_(Bloqueo.profesional_id == current_user.profesional_id, Bloqueo.profesional_id.is_(None)))
    return render_template("panel/bloqueos.html", lista=q.all(), visibles=profesionales_visibles(), hoy=ahora().date())


# ---------- Ajustes ----------

@bp.route("/ajustes", methods=["GET", "POST"])
@requiere("configuracion")
def ajustes_pagina():
    if request.method == "POST":
        f = request.form
        color = f.get("color", "")
        ajustes.guardar({
            "anticipacion_horas": min(720, max(0, f.get("anticipacion_horas", type=int) or 0)),
            "dias_maximo": min(365, max(1, f.get("dias_maximo", type=int) or 60)),
            "intervalo": f.get("intervalo", type=int) if f.get("intervalo", type=int) in (0, 10, 15, 20, 30, 60) else 0,
            "estado_inicial": "pendiente" if f.get("estado_inicial") == "pendiente" else "confirmada",
            "horas_cancelar": min(720, max(0, f.get("horas_cancelar", type=int) or 0)),
            "pedir_rut": bool(f.get("pedir_rut")),
            "email_aviso": f.get("email_aviso", "").strip(),
            "mensaje_confirmacion": f.get("mensaje_confirmacion", "").strip(),
            "color": color if len(color) == 7 and color.startswith("#") else "#2f7a6b",
            "pago_modo": f.get("pago_modo") if f.get("pago_modo") in ("ninguno", "opcional", "obligatorio") else "ninguno",
            "pasarelas": [p for p in f.getlist("pasarelas") if p in ("webpay", "mercadopago")],
            "pago_porcentaje": min(100, max(1, f.get("pago_porcentaje", type=int) or 100)),
            "pago_minutos": min(1440, max(5, f.get("pago_minutos", type=int) or 20)),
            "google_invitar": bool(f.get("google_invitar")),
        })
        flash("Ajustes guardados.", "ok")
        return redirect(url_for("panel.ajustes_pagina"))
    c = current_app.config
    return render_template(
        "panel/ajustes.html",
        a=ajustes.todos(),
        mp_listo=bool(c["MP_ACCESS_TOKEN"]),
        webpay_listo=webpay.disponible(),
        webpay_pruebas=webpay.disponible() and webpay.en_pruebas(),
        whatsapp_listo=whatsapp.configurado(),
        recordatorios_listos=bool(c["CLAVE_TAREAS"]),
        google_configurado=sesiones.google_configurado(),
        google_conectado=sesiones.google_conectado(),
        url_reservar=correos.url_absoluta("publico.reservar_pagina"),
        url_volver_google=correos.url_absoluta("panel.google_volver"),
        url_tareas=correos.url_absoluta("publico.tarea_recordatorios"),
    )


@bp.post("/google/conectar")
@requiere("configuracion")
def google_conectar():
    if not sesiones.google_configurado():
        flash("Faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en Render.", "error")
        return redirect(url_for("panel.ajustes_pagina"))
    session["google_estado"] = estado = secrets.token_urlsafe(24)
    return redirect(sesiones.url_autorizacion(correos.url_absoluta("panel.google_volver"), estado))


@bp.get("/google/volver")
@requiere("configuracion")
def google_volver():
    if not request.args.get("state") or request.args.get("state") != session.pop("google_estado", None):
        flash("La conexión con Google no se pudo verificar. Intenta de nuevo.", "error")
    elif request.args.get("error"):
        flash("Google no dio el permiso.", "error")
    else:
        try:
            sesiones.conectar(request.args.get("code", ""), correos.url_absoluta("panel.google_volver"))
            flash("Google conectado. Las citas online tendrán su enlace de Meet.", "ok")
        except sesiones.GoogleError as e:
            flash(f"No se pudo conectar con Google: {e}", "error")
    return redirect(url_for("panel.ajustes_pagina"))


@bp.post("/google/desconectar")
@requiere("configuracion")
def google_desconectar():
    sesiones.desconectar()
    flash("Google desconectado.", "ok")
    return redirect(url_for("panel.ajustes_pagina"))


# ---------- Mensajes ----------

def _cita_de_ejemplo(online):
    from datetime import timedelta
    from types import SimpleNamespace

    suc = SimpleNamespace(nombre="Providencia", direccion="Av. Providencia 1234, of. 302",
                          indicaciones="Toca el timbre 302. Estacionamiento en el subterráneo.")
    return SimpleNamespace(
        nombre="Camila Pérez", inicio=(ahora() + timedelta(days=2)).replace(hour=10, minute=30, second=0),
        servicio=SimpleNamespace(nombre="Psicoterapia individual"),
        profesional=SimpleNamespace(nombre="Ana Rojas"),
        sucursal=None if online else suc, online=online,
        enlace_sesion="https://meet.google.com/abc-defg-hij" if online else "",
        precio=35000, saldo=35000,
    )


def _vistas(asunto, cuerpo):
    from .. import mensajes

    enlace = correos.url_absoluta("publico.reservar_pagina").replace("/reservar", "/cita/ejemplo")
    vistas = []
    for online in (False, True):
        datos = mensajes.datos_de(_cita_de_ejemplo(online), enlace, 35000)
        vistas.append({"titulo": "Cita online" if online else "Cita presencial",
                       "asunto": mensajes.rellenar(asunto, datos), "cuerpo": mensajes.rellenar(cuerpo, datos)})
    return vistas


@bp.get("/mensajes")
@requiere("configuracion")
def mensajes_lista():
    from .. import mensajes

    lista = [{"clave": k, **v, **mensajes.plantilla(k)} for k, v in mensajes.PLANTILLAS.items()]
    return render_template("panel/mensajes.html", lista=lista)


@bp.route("/mensajes/<clave>", methods=["GET", "POST"])
@requiere("configuracion")
def mensaje_editar(clave):
    from .. import mensajes

    if clave not in mensajes.PLANTILLAS:
        abort(404)
    info = mensajes.PLANTILLAS[clave]
    p = mensajes.plantilla(clave)
    asunto, cuerpo, activo = p["asunto"], p["cuerpo"], p["activo"]

    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "restablecer":
            mensajes.restablecer(clave)
            flash("Volvió al texto original.", "ok")
            return redirect(url_for("panel.mensaje_editar", clave=clave))
        asunto = request.form.get("asunto", "").strip()
        cuerpo = request.form.get("cuerpo", "").replace("\r\n", "\n").strip()
        activo = bool(request.form.get("activo"))
        malos = mensajes.validar(asunto + cuerpo)
        if not cuerpo:
            flash("El mensaje no puede quedar vacío.", "error")
        elif malos:
            flash("Estos campos no existen: " + ", ".join("{" + m + "}" for m in malos) + ". Revisa cómo están escritos.", "error")
        elif accion == "guardar":
            mensajes.guardar(clave, asunto, cuerpo, activo)
            flash("Mensaje guardado. Desde ahora se envía así.", "ok")
            return redirect(url_for("panel.mensaje_editar", clave=clave))
        elif accion == "probar":
            v = _vistas(asunto, cuerpo)[1 if request.form.get("online_prueba") else 0]
            correos.enviar(current_user.email, "[Prueba] " + (v["asunto"] or info["nombre"]), v["cuerpo"])
            flash(f"Te enviamos una prueba a {current_user.email}."
                  + ("" if current_app.config["SMTP_HOST"] else " Ojo: el correo todavía no está configurado, así que no va a llegar."),
                  "ok" if current_app.config["SMTP_HOST"] else "aviso")

    return render_template("panel/mensaje_editar.html", clave=clave, info=info, asunto=asunto, cuerpo=cuerpo,
                           activo=activo, editado=p["editado"], campos=mensajes.CAMPOS, vistas=_vistas(asunto, cuerpo),
                           es_whatsapp=clave.startswith("whatsapp"))
