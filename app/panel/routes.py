"""Panel del equipo. La administración ve y maneja todo; cada profesional ve
su agenda, sus citas, sus bloqueos y su horario."""
import secrets
from datetime import date, datetime, time, timedelta
from functools import wraps

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, or_

from .. import ajustes, correos, sesiones
from ..extensions import db
from ..models import DIAS_SEMANA, ESTADOS, ESTADOS_PAGO, Bloqueo, Cita, Horario, Profesional, Servicio, Usuario
from ..reservas import ReservaError, liberar_horas_sin_pagar, reservar
from ..tiempo import MESES, ahora
from . import bp

COLORES = ["#2f6f8f", "#8a4f9e", "#3d7f4f", "#b0612a", "#a23b5a", "#4a5aa8", "#6b6b2f"]


# ---------- Utilidades ----------

def solo_admin(vista):
    @wraps(vista)
    @login_required
    def envuelta(*a, **kw):
        if not current_user.es_admin:
            abort(403)
        return vista(*a, **kw)
    return envuelta


def mi_profesional_id():
    return None if current_user.es_admin else current_user.profesional_id


def profesionales_visibles(solo_activos=False):
    q = Profesional.query.order_by(Profesional.activo.desc(), Profesional.nombre)
    if solo_activos:
        q = q.filter_by(activo=True)
    if not current_user.es_admin:
        q = q.filter(Profesional.id == current_user.profesional_id)
    return q.all()


def cita_visible(cita_id):
    c = db.session.get(Cita, cita_id)
    if not c or (not current_user.es_admin and c.profesional_id != current_user.profesional_id):
        abort(404)
    return c


def color_de(prof_id):
    return COLORES[(prof_id or 0) % len(COLORES)]


def _fecha(valor, defecto):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return defecto


def _hora(valor):
    try:
        return datetime.strptime(valor, "%H:%M").time()
    except (TypeError, ValueError):
        return None


@bp.app_context_processor
def datos_panel():
    return {"ESTADOS": ESTADOS, "ESTADOS_PAGO": ESTADOS_PAGO, "color_de": color_de, "DIAS_SEMANA": DIAS_SEMANA}


# ---------- Entrar y salir ----------

def _serializador():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="restablecer-clave")


@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if current_user.is_authenticated:
        return redirect(url_for("panel.agenda"))
    if request.method == "POST":
        u = Usuario.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if u and u.activo and u.revisar_clave(request.form.get("clave", "")):
            login_user(u, remember=True)
            destino = request.args.get("next", "")
            return redirect(destino if destino.startswith("/panel") else url_for("panel.agenda"))
        flash("El correo o la contraseña no coinciden.", "error")
    return render_template("panel/entrar.html")


@bp.post("/salir")
@login_required
def salir():
    logout_user()
    return redirect(url_for("panel.entrar"))


@bp.route("/olvide", methods=["GET", "POST"])
def olvide():
    if request.method == "POST":
        u = Usuario.query.filter_by(email=request.form.get("email", "").strip().lower(), activo=True).first()
        if u:
            token = _serializador().dumps({"u": u.id, "h": u.clave_hash[-12:]})
            correos.restablecer_clave(u, correos.url_absoluta("panel.restablecer", token=token))
        flash("Si el correo tiene una cuenta, te llegó un enlace para cambiar la contraseña.", "ok")
        return redirect(url_for("panel.entrar"))
    return render_template("panel/olvide.html")


@bp.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer(token):
    try:
        datos = _serializador().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("El enlace venció o no es válido. Pide uno nuevo.", "error")
        return redirect(url_for("panel.olvide"))
    u = db.session.get(Usuario, datos.get("u"))
    if not u or u.clave_hash[-12:] != datos.get("h"):
        flash("Este enlace ya se usó. Pide uno nuevo.", "error")
        return redirect(url_for("panel.olvide"))
    if request.method == "POST":
        clave = request.form.get("clave", "")
        if len(clave) < 8:
            flash("La contraseña necesita al menos 8 caracteres.", "error")
        else:
            u.poner_clave(clave)
            db.session.commit()
            flash("Listo. Ya puedes entrar con tu contraseña nueva.", "ok")
            return redirect(url_for("panel.entrar"))
    return render_template("panel/restablecer.html")


@bp.route("/cuenta", methods=["GET", "POST"])
@login_required
def cuenta():
    if request.method == "POST":
        if not current_user.revisar_clave(request.form.get("actual", "")):
            flash("La contraseña actual no coincide.", "error")
        elif len(request.form.get("nueva", "")) < 8:
            flash("La contraseña nueva necesita al menos 8 caracteres.", "error")
        else:
            current_user.poner_clave(request.form["nueva"])
            db.session.commit()
            flash("Contraseña cambiada.", "ok")
            return redirect(url_for("panel.cuenta"))
    return render_template("panel/cuenta.html")


# ---------- Agenda semanal ----------

@bp.get("/")
@login_required
def agenda():
    liberar_horas_sin_pagar()
    hoy = ahora().date()
    base = _fecha(request.args.get("semana"), hoy)
    lunes = base - timedelta(days=base.weekday())
    dias = [lunes + timedelta(days=i) for i in range(7)]

    visibles = profesionales_visibles(solo_activos=True)
    elegido = request.args.get("profesional", type=int) if current_user.es_admin else current_user.profesional_id
    mostrados = [p for p in visibles if not elegido or p.id == elegido]
    ids = [p.id for p in mostrados]

    ini = datetime.combine(lunes, time())
    fin = ini + timedelta(days=7)
    citas = (Cita.query.filter(Cita.profesional_id.in_(ids), Cita.inicio >= ini, Cita.inicio < fin, Cita.estado != "cancelada")
             .order_by(Cita.inicio).all()) if ids else []
    bloqueos = Bloqueo.query.filter(
        or_(Bloqueo.profesional_id.is_(None), Bloqueo.profesional_id.in_(ids or [0])), Bloqueo.inicio < fin, Bloqueo.fin > ini
    ).all()

    # Rango de horas: el de los horarios, ampliado si hay citas fuera de él.
    h0, h1 = 9 * 60, 19 * 60
    tramos = [h for p in mostrados for h in p.horarios]
    if tramos:
        h0 = min(h.inicio.hour * 60 + h.inicio.minute for h in tramos)
        h1 = max(h.fin.hour * 60 + h.fin.minute for h in tramos)
    for c in citas:
        h0 = min(h0, c.inicio.hour * 60 + c.inicio.minute)
        h1 = max(h1, c.fin.hour * 60 + c.fin.minute if c.fin.date() == c.inicio.date() else 24 * 60)
    h0, h1 = (h0 // 60) * 60, min(24 * 60, -(-h1 // 60) * 60)
    total = max(60, h1 - h0)

    def posicion(a, b):
        ma = max(h0, a.hour * 60 + a.minute)
        mb = min(h1, b.hour * 60 + b.minute if b.date() == a.date() else 24 * 60)
        return {"top": round((ma - h0) / total * 100, 3), "alto": round(max(mb - ma, 10) / total * 100, 3)}

    columnas = []
    for d in dias:
        del_dia = [c for c in citas if c.inicio.date() == d]
        # Citas que se topan (varios profesionales a la misma hora) van lado a lado.
        carriles = []
        bloques = []
        for c in del_dia:
            for i, termina in enumerate(carriles):
                if termina <= c.inicio:
                    carriles[i] = c.fin
                    break
            else:
                i = len(carriles)
                carriles.append(c.fin)
            bloques.append({"cita": c, "carril": i, **posicion(c.inicio, c.fin)})
        for b in bloques:
            b["carriles"] = len(carriles)
        grises = []
        for b in bloqueos:
            a = max(b.inicio, datetime.combine(d, time()) + timedelta(minutes=h0))
            z = min(b.fin, datetime.combine(d, time()) + timedelta(minutes=h1))
            if a < z:
                grises.append({"motivo": b.motivo, **posicion(a, z)})
        columnas.append({"dia": d, "bloques": bloques, "bloqueos": grises, "hoy": d == hoy})

    linea_ahora = None
    if lunes <= hoy < lunes + timedelta(days=7):
        m = ahora().hour * 60 + ahora().minute
        if h0 <= m <= h1:
            linea_ahora = round((m - h0) / total * 100, 3)

    return render_template(
        "panel/agenda.html",
        columnas=columnas,
        horas=list(range(h0 // 60, h1 // 60)),
        alto_hora=round(100 / (total / 60), 4),
        lunes=lunes,
        semana_anterior=lunes - timedelta(days=7),
        semana_siguiente=lunes + timedelta(days=7),
        hoy=hoy,
        visibles=visibles,
        elegido=elegido,
        linea_ahora=linea_ahora,
        citas_semana=len(citas),
        rango=_rango(lunes, dias[-1]),
    )


def _rango(a, z):
    if a.month == z.month:
        return f"{a.day} – {z.day} de {MESES[z.month - 1]} {z.year}"
    return f"{a.day} de {MESES[a.month - 1]} – {z.day} de {MESES[z.month - 1]} {z.year}"


# ---------- Citas ----------

@bp.get("/citas")
@login_required
def citas():
    hoy = ahora().date()
    desde = _fecha(request.args.get("desde"), hoy)
    hasta = max(desde, _fecha(request.args.get("hasta"), hoy + timedelta(days=6)))
    q = Cita.query.filter(Cita.inicio >= datetime.combine(desde, time()), Cita.inicio < datetime.combine(hasta + timedelta(days=1), time()))
    prof = request.args.get("profesional", type=int) if current_user.es_admin else current_user.profesional_id
    if prof:
        q = q.filter(Cita.profesional_id == prof)
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
    return render_template("panel/citas.html", por_dia=por_dia, total=len(lista), desde=desde, hasta=hasta,
                           prof=prof, estado=estado, texto=texto, visibles=profesionales_visibles())


@bp.route("/citas/nueva", methods=["GET", "POST"])
@login_required
def cita_nueva():
    servicios = Servicio.query.order_by(Servicio.activo.desc(), Servicio.nombre).all()
    visibles = profesionales_visibles(solo_activos=True)
    datos = request.form.to_dict() if request.method == "POST" else {
        "fecha": request.args.get("fecha", ahora().date().isoformat()),
        "hora": request.args.get("hora", ""),
        "profesional_id": str(request.args.get("profesional", type=int) or mi_profesional_id() or ""),
        "estado": "confirmada",
        "avisar": "1",
    }
    if request.method == "POST":
        if not current_user.es_admin:
            datos["profesional_id"] = str(current_user.profesional_id)
        try:
            c = reservar(datos, desde_panel=True)
        except ReservaError as e:
            flash(str(e), "error")
        else:
            if datos.get("avisar"):
                correos.nueva_cita(c)
            else:
                sesiones.asegurar(c)
            flash("Cita creada.", "ok")
            return redirect(url_for("panel.cita", cita_id=c.id))
    return render_template("panel/cita_nueva.html", servicios=servicios, visibles=visibles, d=datos)


@bp.route("/citas/<int:cita_id>", methods=["GET", "POST"])
@login_required
def cita(cita_id):
    c = cita_visible(cita_id)
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "estado":
            nuevo = request.form.get("estado")
            if nuevo in ESTADOS and nuevo != c.estado:
                c.estado = nuevo
                if nuevo != "cancelada":
                    c.expira = None  # Confirmada a mano: deja de esperar el pago.
                db.session.commit()
                if nuevo == "cancelada":
                    sesiones.cancelar(c)
                else:
                    sesiones.asegurar(c)
                if request.form.get("avisar") and nuevo in ("confirmada", "cancelada"):
                    correos.estado_cambiado(c)
                flash(f"Estado: {ESTADOS[nuevo]}.", "ok")
        elif accion == "pagado":
            c.estado_pago = "pagado"
            c.expira = None
            if not c.monto:
                c.monto = c.servicio.precio
            if c.estado == "pendiente":
                c.estado = "confirmada"
            db.session.commit()
            sesiones.asegurar(c)
            flash("Marcada como pagada.", "ok")
        elif accion == "nota":
            c.nota_interna = request.form.get("nota_interna", "")[:5000]
            db.session.commit()
            flash("Nota guardada.", "ok")
        elif accion == "enlace":
            c.enlace_sesion = request.form.get("enlace_sesion", "").strip()[:500]
            db.session.commit()
            flash("Enlace guardado.", "ok")
        elif accion == "crear_meet":
            c.enlace_sesion = ""
            db.session.commit()
            sesiones.asegurar(c)
            flash("Enlace de sesión creado." if c.enlace_sesion else "No se pudo crear el Meet. Revisa la conexión con Google en Ajustes.",
                  "ok" if c.enlace_sesion else "error")
        elif accion == "reenviar":
            correos.nueva_cita(c)
            flash("Confirmación reenviada al paciente.", "ok")
        elif accion == "borrar":
            sesiones.cancelar(c)
            db.session.delete(c)
            db.session.commit()
            flash("Cita borrada.", "ok")
            return redirect(url_for("panel.agenda", semana=c.inicio.date().isoformat()))
        return redirect(url_for("panel.cita", cita_id=c.id))

    historial = (Cita.query.filter(func.lower(Cita.email) == c.email.lower(), Cita.id != c.id)
                 .order_by(Cita.inicio.desc()).limit(20).all())
    if not current_user.es_admin:
        historial = [h for h in historial if h.profesional_id == current_user.profesional_id]
    return render_template("panel/cita.html", c=c, historial=historial,
                           enlace_paciente=correos.url_absoluta("publico.cita", token=c.token),
                           google=sesiones.google_conectado())


# ---------- Pacientes ----------

@bp.get("/pacientes")
@login_required
def pacientes():
    texto = request.args.get("q", "").strip()
    q = db.session.query(
        func.lower(Cita.email).label("email"),
        func.max(Cita.nombre).label("nombre"),
        func.max(Cita.rut).label("rut"),
        func.max(Cita.telefono).label("telefono"),
        func.count(Cita.id).label("citas"),
        func.max(Cita.inicio).label("ultima"),
    )
    if not current_user.es_admin:
        q = q.filter(Cita.profesional_id == current_user.profesional_id)
    if texto:
        like = f"%{texto}%"
        q = q.filter(or_(Cita.nombre.ilike(like), Cita.email.ilike(like), Cita.rut.ilike(like), Cita.telefono.ilike(like)))
    filas = q.group_by(func.lower(Cita.email)).order_by(func.max(Cita.inicio).desc()).limit(300).all()
    return render_template("panel/pacientes.html", filas=filas, texto=texto)


# ---------- Servicios ----------

@bp.route("/servicios", methods=["GET", "POST"])
@bp.route("/servicios/<int:servicio_id>", methods=["GET", "POST"])
@solo_admin
def servicios(servicio_id=None):
    s = db.session.get(Servicio, servicio_id) if servicio_id else Servicio(duracion=45, precio=0, modalidad="presencial", activo=True)
    if servicio_id and not s:
        abort(404)
    if request.method == "POST":
        if request.form.get("accion") == "borrar" and s.id:
            if Cita.query.filter_by(servicio_id=s.id).first():
                s.activo = False
                flash("Tiene citas registradas, así que no se borró: quedó inactivo y ya no aparece al reservar.", "aviso")
            else:
                db.session.delete(s)
                flash("Servicio borrado.", "ok")
            db.session.commit()
            return redirect(url_for("panel.servicios"))
        s.nombre = request.form.get("nombre", "").strip()[:190]
        s.descripcion = request.form.get("descripcion", "").strip()
        s.duracion = min(600, max(5, request.form.get("duracion", type=int) or 45))
        s.precio = max(0, request.form.get("precio", type=int) or 0)
        s.modalidad = "online" if request.form.get("modalidad") == "online" else "presencial"
        s.activo = bool(request.form.get("activo"))
        if not s.nombre:
            flash("El servicio necesita un nombre.", "error")
        else:
            db.session.add(s)
            db.session.commit()
            flash("Servicio guardado.", "ok")
            return redirect(url_for("panel.servicios"))
    lista = Servicio.query.order_by(Servicio.activo.desc(), Servicio.nombre).all()
    return render_template("panel/servicios.html", lista=lista, s=s)


# ---------- Profesionales ----------

@bp.get("/profesionales")
@solo_admin
def profesionales():
    return render_template("panel/profesionales.html", lista=profesionales_visibles())


@bp.route("/profesionales/nuevo", methods=["GET", "POST"])
@bp.route("/profesionales/<int:prof_id>", methods=["GET", "POST"])
@login_required
def profesional(prof_id=None):
    if prof_id is None and not current_user.es_admin:
        abort(403)
    if prof_id is not None and not current_user.es_admin and prof_id != current_user.profesional_id:
        abort(403)
    p = db.session.get(Profesional, prof_id) if prof_id else Profesional(activo=True)
    if prof_id and not p:
        abort(404)
    admin = current_user.es_admin
    todos_servicios = Servicio.query.order_by(Servicio.nombre).all()

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

        # Horario: hasta dos tramos por día.
        tramos = []
        for dia in range(7):
            for i in range(2):
                a, z = request.form.get(f"h-{dia}-{i}-ini", ""), request.form.get(f"h-{dia}-{i}-fin", "")
                if not a and not z:
                    continue
                ta, tz = _hora(a), _hora(z)
                if not ta or not tz or tz <= ta:
                    flash(f"Revisa el horario del {DIAS_SEMANA[dia].lower()}: cada tramo tiene que terminar después de empezar.", "error")
                    return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, tramos=_tramos_form(), admin=admin)
                tramos.append((dia, ta, tz))

        p.enlace_sala = request.form.get("enlace_sala", "").strip()[:500]
        if admin:
            p.nombre = request.form.get("nombre", "").strip()[:190]
            p.titulo = request.form.get("titulo", "").strip()[:190]
            p.email = request.form.get("email", "").strip().lower()[:190]
            p.activo = bool(request.form.get("activo"))
            elegidos = {int(x) for x in request.form.getlist("servicios") if x.isdigit()}
            p.servicios = [s for s in todos_servicios if s.id in elegidos]
            if not p.nombre:
                flash("Falta el nombre.", "error")
                return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, tramos=_tramos_form(), admin=admin)

        db.session.add(p)
        db.session.flush()
        Horario.query.filter_by(profesional_id=p.id).delete()
        for dia, ta, tz in tramos:
            db.session.add(Horario(profesional_id=p.id, dia=dia, inicio=ta, fin=tz))

        clave_nueva = None
        if admin and request.form.get("acceso"):
            if not p.email:
                db.session.rollback()
                flash("Para darle acceso al panel, escribe su correo.", "error")
                return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, tramos=_tramos_form(), admin=admin)
            u = p.usuario
            otro = Usuario.query.filter(func.lower(Usuario.email) == p.email, Usuario.profesional_id != p.id).first()
            if otro:
                db.session.rollback()
                flash("Ese correo ya lo usa otra cuenta.", "error")
                return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, tramos=_tramos_form(), admin=admin)
            if u is None:
                u = Usuario(email=p.email, nombre=p.nombre, rol="profesional", profesional=p)
                clave_nueva = secrets.token_urlsafe(9)
                u.poner_clave(clave_nueva)
                db.session.add(u)
            u.email, u.nombre, u.activo = p.email, p.nombre, p.activo
        elif admin and p.usuario:
            p.usuario.activo = False

        db.session.commit()
        if clave_nueva:
            session["clave_mostrar"] = {"email": p.email, "clave": clave_nueva}
            token = _serializador().dumps({"u": p.usuario.id, "h": p.usuario.clave_hash[-12:]})
            correos.enviar(
                p.email,
                f"Tu acceso a la agenda de {current_app.config['NOMBRE_NEGOCIO']}",
                f"Hola {p.nombre},\n\nYa tienes acceso a tu agenda en Reservared.\n\n"
                f"Elige tu contraseña aquí (el enlace vale una hora):\n{correos.url_absoluta('panel.restablecer', token=token)}\n\n"
                f"Después entras en: {correos.url_absoluta('panel.entrar')}\nTu usuario es: {p.email}",
            )
        flash("Guardado.", "ok")
        return redirect(url_for("panel.profesional", prof_id=p.id))

    tramos = {}
    for h in p.horarios if p.id else []:
        tramos.setdefault(h.dia, []).append((h.inicio.strftime("%H:%M"), h.fin.strftime("%H:%M")))
    if not p.id:
        tramos = {d: [("09:00", "13:00"), ("15:00", "19:00")] for d in range(5)}
    return render_template("panel/profesional.html", p=p, todos_servicios=todos_servicios, tramos=tramos, admin=admin,
                           clave_mostrar=session.pop("clave_mostrar", None))


def _tramos_form():
    tramos = {}
    for dia in range(7):
        for i in range(2):
            a, z = request.form.get(f"h-{dia}-{i}-ini", ""), request.form.get(f"h-{dia}-{i}-fin", "")
            if a or z:
                tramos.setdefault(dia, []).append((a, z))
    return tramos


@bp.get("/mi-horario")
@login_required
def mi_horario():
    if current_user.es_admin or not current_user.profesional_id:
        return redirect(url_for("panel.profesionales"))
    return redirect(url_for("panel.profesional", prof_id=current_user.profesional_id))


# ---------- Bloqueos ----------

@bp.route("/bloqueos", methods=["GET", "POST"])
@login_required
def bloqueos():
    if request.method == "POST":
        if request.form.get("accion") == "borrar":
            b = db.session.get(Bloqueo, request.form.get("id", type=int) or 0)
            if b and (current_user.es_admin or b.profesional_id == current_user.profesional_id):
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
            prof = (request.form.get("profesional_id", type=int) or None) if current_user.es_admin else current_user.profesional_id
            db.session.add(Bloqueo(profesional_id=prof, inicio=a, fin=z, motivo=request.form.get("motivo", "").strip()[:190]))
            db.session.commit()
            flash("Bloqueo agregado. Esas horas ya no se ofrecen.", "ok")
        return redirect(url_for("panel.bloqueos"))

    q = Bloqueo.query.filter(Bloqueo.fin >= ahora()).order_by(Bloqueo.inicio)
    if not current_user.es_admin:
        q = q.filter(or_(Bloqueo.profesional_id == current_user.profesional_id, Bloqueo.profesional_id.is_(None)))
    return render_template("panel/bloqueos.html", lista=q.all(), visibles=profesionales_visibles(), hoy=ahora().date())


# ---------- Equipo de administración ----------

@bp.route("/equipo", methods=["GET", "POST"])
@solo_admin
def equipo():
    if request.method == "POST":
        if request.form.get("accion") == "borrar":
            u = db.session.get(Usuario, request.form.get("id", type=int) or 0)
            if u and u.es_admin and u.id != current_user.id:
                db.session.delete(u)
                db.session.commit()
                flash("Cuenta borrada.", "ok")
            return redirect(url_for("panel.equipo"))
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        if not email or "@" not in email or not nombre:
            flash("Escribe nombre y correo.", "error")
        elif Usuario.query.filter(func.lower(Usuario.email) == email).first():
            flash("Ese correo ya tiene cuenta.", "error")
        else:
            u = Usuario(email=email, nombre=nombre, rol="admin")
            u.poner_clave(secrets.token_urlsafe(16))
            db.session.add(u)
            db.session.commit()
            token = _serializador().dumps({"u": u.id, "h": u.clave_hash[-12:]})
            correos.enviar(email, "Tu acceso a Reservared",
                           f"Hola {nombre},\n\nTe dieron acceso de administración a Reservared.\n\n"
                           f"Elige tu contraseña aquí (vale una hora):\n{correos.url_absoluta('panel.restablecer', token=token)}")
            flash(f"Cuenta creada. Le enviamos a {email} un enlace para elegir su contraseña.", "ok")
        return redirect(url_for("panel.equipo"))
    admins = Usuario.query.filter_by(rol="admin").order_by(Usuario.nombre).all()
    return render_template("panel/equipo.html", admins=admins)


# ---------- Ajustes ----------

@bp.route("/ajustes", methods=["GET", "POST"])
@solo_admin
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
            "color": color if len(color) == 7 and color.startswith("#") else "#1f6f78",
            "pago_modo": f.get("pago_modo") if f.get("pago_modo") in ("ninguno", "opcional", "obligatorio") else "ninguno",
            "pago_porcentaje": min(100, max(1, f.get("pago_porcentaje", type=int) or 100)),
            "pago_minutos": min(1440, max(5, f.get("pago_minutos", type=int) or 20)),
            "google_invitar": bool(f.get("google_invitar")),
        })
        flash("Ajustes guardados.", "ok")
        return redirect(url_for("panel.ajustes_pagina"))
    return render_template(
        "panel/ajustes.html",
        a=ajustes.todos(),
        mp_listo=bool(current_app.config["MP_ACCESS_TOKEN"]),
        google_configurado=sesiones.google_configurado(),
        google_conectado=sesiones.google_conectado(),
        url_reservar=correos.url_absoluta("publico.reservar_pagina"),
        url_aviso_mp=correos.url_absoluta("publico.aviso_mercadopago"),
        url_volver_google=correos.url_absoluta("panel.google_volver"),
    )


@bp.post("/google/conectar")
@solo_admin
def google_conectar():
    if not sesiones.google_configurado():
        flash("Faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en Render.", "error")
        return redirect(url_for("panel.ajustes_pagina"))
    session["google_estado"] = estado = secrets.token_urlsafe(24)
    return redirect(sesiones.url_autorizacion(correos.url_absoluta("panel.google_volver"), estado))


@bp.get("/google/volver")
@solo_admin
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
@solo_admin
def google_desconectar():
    sesiones.desconectar()
    flash("Google desconectado.", "ok")
    return redirect(url_for("panel.ajustes_pagina"))
