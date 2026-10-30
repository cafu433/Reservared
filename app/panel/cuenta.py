"""Entrar, salir y contraseñas."""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired

from .. import correos
from ..extensions import db
from ..models import Usuario
from . import bp
from .comun import enlace_clave, serializador


def inicio_de(usuario):
    """La primera pantalla según los permisos."""
    for permiso, endpoint in (("dashboard", "panel.dashboard"), ("agenda", "panel.agenda"),
                              ("agendar", "panel.agendar"), ("pacientes", "panel.pacientes"),
                              ("cobranza", "panel.cobranza")):
        if usuario.puede(permiso):
            return url_for(endpoint)
    return url_for("panel.cuenta")


@bp.get("/")
@login_required
def inicio():
    return redirect(inicio_de(current_user))


@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if current_user.is_authenticated:
        return redirect(inicio_de(current_user))
    if request.method == "POST":
        u = Usuario.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if u and u.activo and u.revisar_clave(request.form.get("clave", "")):
            login_user(u, remember=True)
            destino = request.args.get("next", "")
            return redirect(destino if destino.startswith("/panel") else inicio_de(u))
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
            correos.restablecer_clave(u, enlace_clave(u))
        flash("Si el correo tiene una cuenta, te llegó un enlace para cambiar la contraseña.", "ok")
        return redirect(url_for("panel.entrar"))
    return render_template("panel/olvide.html")


@bp.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer(token):
    try:
        datos = serializador().loads(token, max_age=3600)
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
