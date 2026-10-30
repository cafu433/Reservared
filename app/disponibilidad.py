"""Qué horas quedan libres.

Carga de una vez los horarios, las citas y los bloqueos del rango y calcula en
memoria.
"""
from datetime import datetime, timedelta

from sqlalchemy import or_

from . import ajustes
from .extensions import db
from .models import Bloqueo, Cita
from .tiempo import ahora


def filtro_ocupa():
    """Citas que ocupan su hora: no canceladas y sin un plazo de pago vencido."""
    return db.and_(Cita.estado != "cancelada", or_(Cita.expira.is_(None), Cita.expira > ahora()))


def modalidad_de(servicio, pedida=None):
    """La modalidad de la cita: la del servicio, o la que se pidió si el
    servicio admite las dos."""
    if servicio.modalidad != "ambas":
        return servicio.modalidad
    return pedida if pedida in ("presencial", "online") else None


def tramo_sirve(h, modalidad, sucursal_id):
    """El tramo tiene que admitir la modalidad (online, presencial o ambas).
    Para lo presencial, además, la sucursal: un tramo sin sucursal sirve en
    cualquiera."""
    if not h.sirve_para(modalidad):
        return False
    return modalidad == "online" or not sucursal_id or h.sucursal_id in (None, sucursal_id)


def sucursal_en(profesional, modalidad, inicio, fin, sucursal_id=None):
    """La sucursal del tramo de horario donde cae la cita (None si es online)."""
    if modalidad == "online":
        return None
    for h in profesional.horarios:
        if (h.dia == inicio.weekday() and h.inicio <= inicio.time() and fin.time() <= h.fin
                and tramo_sirve(h, modalidad, sucursal_id)):
            return h.sucursal_id or sucursal_id
    return sucursal_id


def calcular(servicio, profesionales, desde, hasta, sucursal_id=None, equipo=False, modalidad=None, especialidad_id=None):
    """
    :param servicio: Servicio.
    :param profesionales: lista de Profesional.
    :param desde, hasta: date, ambos incluidos.
    :param sucursal_id: sólo los tramos de esa sucursal.
    :param equipo: True desde el panel: sin anticipación mínima ni tope de días.
    :param modalidad: presencial | online (sólo cuenta si el servicio admite las dos).
    :param especialidad_id: sólo profesionales con esa especialidad.
    :return: {date: {"HH:MM": [profesional_id, …]}}
    """
    profesionales = [p for p in profesionales if p.atiende(servicio)
                     and (not especialidad_id or any(e.id == especialidad_id for e in p.especialidades))]
    modalidad = modalidad_de(servicio, modalidad)
    if not profesionales or servicio is None:
        return {}

    aj = ajustes.todos()
    momento = ahora()
    minimo = momento if equipo else momento + timedelta(hours=max(0, int(aj["anticipacion_horas"])))
    ultimo = hasta if equipo else momento.date() + timedelta(days=max(0, int(aj["dias_maximo"])))
    desde = max(desde, momento.date())
    hasta = min(hasta, ultimo)
    if desde > hasta:
        return {}

    ids = [p.id for p in profesionales]
    rango_ini = datetime.combine(desde, datetime.min.time())
    rango_fin = datetime.combine(hasta + timedelta(days=1), datetime.min.time())

    ocupado = {pid: [] for pid in ids}
    citas = (
        db.session.query(Cita.profesional_id, Cita.inicio, Cita.fin)
        .filter(Cita.profesional_id.in_(ids), Cita.inicio < rango_fin, Cita.fin > rango_ini, filtro_ocupa())
        .all()
    )
    for pid, ini, fin in citas:
        ocupado[pid].append((ini, fin))
    bloqueos = Bloqueo.query.filter(
        or_(Bloqueo.profesional_id.is_(None), Bloqueo.profesional_id.in_(ids)),
        Bloqueo.inicio < rango_fin,
        Bloqueo.fin > rango_ini,
    ).all()
    for b in bloqueos:
        for pid in ([b.profesional_id] if b.profesional_id else ids):
            ocupado[pid].append((b.inicio, b.fin))

    duracion = timedelta(minutes=max(5, servicio.duracion))
    paso = timedelta(minutes=int(aj["intervalo"]) or max(5, servicio.duracion))

    resultado = {}
    dia = desde
    while dia <= hasta:
        horas = {}
        for p in profesionales:
            for h in p.horarios:
                if h.dia != dia.weekday() or not tramo_sirve(h, modalidad, sucursal_id):
                    continue
                t = datetime.combine(dia, h.inicio)
                fin_tramo = datetime.combine(dia, h.fin)
                while t + duracion <= fin_tramo:
                    f = t + duracion
                    if t >= minimo and not any(t < o_fin and o_ini < f for o_ini, o_fin in ocupado[p.id]):
                        horas.setdefault(t.strftime("%H:%M"), []).append(p.id)
                    t += paso
        if horas:
            resultado[dia] = dict(sorted(horas.items()))
        dia += timedelta(days=1)
    return resultado
