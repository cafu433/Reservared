"""Ayudas que comparten los módulos del panel."""
from datetime import date, datetime

from flask import abort, current_app
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import or_

from ..extensions import db
from ..models import (DIAS_SEMANA, ESTADOS, ESTADOS_PAGO, MEDIOS_PAGO, MODALIDADES_TRAMO, MOTIVOS_CANCELACION,
                      PREVISIONES, Cita, Paciente, Profesional, Sucursal)
from ..permisos import PERMISOS
from . import bp

COLORES = ["#2f6f8f", "#8a4f9e", "#3d7f4f", "#b0612a", "#a23b5a", "#4a5aa8", "#6b6b2f", "#2f7f7a"]


def color_de(prof_id):
    return COLORES[(prof_id or 0) % len(COLORES)]


@bp.app_context_processor
def datos_panel():
    return {
        "ESTADOS": ESTADOS, "ESTADOS_PAGO": ESTADOS_PAGO, "MEDIOS_PAGO": MEDIOS_PAGO, "DIAS_SEMANA": DIAS_SEMANA,
        "MODALIDADES_TRAMO": MODALIDADES_TRAMO, "MOTIVOS_CANCELACION": MOTIVOS_CANCELACION, "PREVISIONES": PREVISIONES,
        "PERMISOS": PERMISOS, "color_de": color_de,
    }


def fecha(valor, defecto):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return defecto


def hora(valor):
    try:
        return datetime.strptime(valor, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def entero(valor):
    try:
        return int(str(valor).replace(".", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def profesionales_visibles(solo_activos=False):
    """Todos si la cuenta ve todo el equipo; si no, sólo su propio perfil."""
    q = Profesional.query.order_by(Profesional.activo.desc(), Profesional.nombre)
    if solo_activos:
        q = q.filter_by(activo=True)
    if not current_user.ve_todo:
        q = q.filter(Profesional.id == current_user.profesional_id)
    return q.all()


def filtro_citas_propias(q):
    if not current_user.ve_todo:
        q = q.filter(Cita.profesional_id == current_user.profesional_id)
    return q


def cita_visible(cita_id):
    c = db.session.get(Cita, cita_id)
    if not c or (not current_user.ve_todo and c.profesional_id != current_user.profesional_id):
        abort(404)
    return c


def paciente_visible(paciente_id):
    p = db.session.get(Paciente, paciente_id)
    if not p:
        abort(404)
    if not current_user.ve_todo and not p.citas.filter(Cita.profesional_id == current_user.profesional_id).first():
        abort(404)
    return p


def pacientes_visibles():
    q = Paciente.query
    if not current_user.ve_todo:
        q = q.filter(Paciente.citas.any(Cita.profesional_id == current_user.profesional_id))
    return q


def buscar_pacientes(q, texto):
    like = f"%{texto}%"
    return q.filter(or_(Paciente.nombre.ilike(like), Paciente.rut.ilike(like), Paciente.email.ilike(like),
                        Paciente.telefono.ilike(like)))


def sucursales(solo_activas=True):
    q = Sucursal.query.order_by(Sucursal.nombre)
    return q.filter_by(activa=True).all() if solo_activas else q.all()


def serializador():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="restablecer-clave")


def enlace_clave(usuario):
    from ..correos import url_absoluta

    token = serializador().dumps({"u": usuario.id, "h": usuario.clave_hash[-12:]})
    return url_absoluta("panel.restablecer", token=token)
