"""Números del dashboard. Se calculan en memoria sobre las citas del periodo:
para una consulta o un centro mediano son unas pocas miles de filas."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from .models import Bloqueo, Cita, Paciente, Pago
from .tiempo import ahora


def _min(t):
    return t.hour * 60 + t.minute


def _pct(a, b):
    return round(100 * a / b) if b else None


def minutos_disponibles(profesionales, desde, hasta, sucursal_id=None):
    """Minutos de horario de atención en el periodo, descontando bloqueos de día completo."""
    total = 0
    bloqueos = Bloqueo.query.filter(Bloqueo.inicio < datetime.combine(hasta + timedelta(days=1), time()),
                                    Bloqueo.fin > datetime.combine(desde, time())).all()
    dia = desde
    while dia <= hasta:
        for p in profesionales:
            bloqueado = any(b.profesional_id in (None, p.id) and b.inicio <= datetime.combine(dia, time(0, 1))
                            and b.fin >= datetime.combine(dia, time(23, 58)) for b in bloqueos)
            if bloqueado:
                continue
            for h in p.horarios:
                if h.dia == dia.weekday() and (not sucursal_id or h.sucursal_id in (None, sucursal_id) or h.modalidad == "online"):
                    total += _min(h.fin) - _min(h.inicio)
        dia += timedelta(days=1)
    return total


def resumen(citas, pagos, profesionales, desde, hasta, sucursal_id=None):
    momento = ahora()
    activas = [c for c in citas if c.estado != "cancelada"]
    pasadas = [c for c in activas if c.inicio <= momento]
    asistio = sum(1 for c in citas if c.estado == "asistio")
    no_asistio = sum(1 for c in citas if c.estado == "no_asistio")
    canceladas = [c for c in citas if c.estado == "cancelada"]

    anticipacion = Counter()
    for c in canceladas:
        if not c.cancelada_en:
            anticipacion["Sin dato"] += 1
            continue
        horas = (c.inicio - c.cancelada_en).total_seconds() / 3600
        anticipacion["Menos de 24 h" if horas < 24 else "24 a 72 h" if horas < 72 else "Más de 72 h"] += 1

    minutos_ocupados = sum((c.fin - c.inicio).total_seconds() / 60 for c in activas)
    disponibles = minutos_disponibles(profesionales, desde, hasta, sucursal_id)

    por_dia = defaultdict(lambda: {"citas": 0, "canceladas": 0})
    for c in citas:
        por_dia[c.inicio.date()]["canceladas" if c.estado == "cancelada" else "citas"] += 1
    serie = []
    d = desde
    while d <= hasta:
        serie.append({"dia": d, **por_dia[d]})
        d += timedelta(days=1)

    por_prof = {}
    for p in profesionales:
        por_prof[p.id] = {"nombre": p.nombre, "citas": 0, "asistio": 0, "no_asistio": 0, "canceladas": 0,
                          "minutos": 0, "disponibles": minutos_disponibles([p], desde, hasta, sucursal_id), "cobrado": 0}
    for c in citas:
        f = por_prof.get(c.profesional_id)
        if not f:
            continue
        if c.estado == "cancelada":
            f["canceladas"] += 1
            continue
        f["citas"] += 1
        f["minutos"] += (c.fin - c.inicio).total_seconds() / 60
        f["asistio"] += c.estado == "asistio"
        f["no_asistio"] += c.estado == "no_asistio"
    for pg in pagos:
        if pg.profesional_id in por_prof:
            por_prof[pg.profesional_id]["cobrado"] += pg.monto
    for f in por_prof.values():
        f["ocupacion"] = _pct(f["minutos"], f["disponibles"])

    por_servicio = Counter()
    por_categoria = Counter()
    por_sucursal = Counter()
    for c in activas:
        por_servicio[c.servicio.nombre] += 1
        por_categoria[c.servicio.categoria or "Sin tipo"] += 1
        por_sucursal["Online" if c.online else (c.sucursal.nombre if c.sucursal else "Sin sucursal")] += 1

    pacientes_ids = {c.paciente_id for c in activas if c.paciente_id}
    nuevos = Paciente.query.filter(Paciente.creado >= datetime.combine(desde, time()),
                                   Paciente.creado < datetime.combine(hasta + timedelta(days=1), time())).count()

    return {
        "total": len(citas),
        "activas": len(activas),
        "asistio": asistio,
        "no_asistio": no_asistio,
        "pct_asistencia": _pct(asistio, asistio + no_asistio),
        "pct_inasistencia": _pct(no_asistio, asistio + no_asistio),
        "sin_marcar": sum(1 for c in pasadas if c.estado in ("confirmada", "pendiente")),
        "canceladas": len(canceladas),
        "pct_cancelacion": _pct(len(canceladas), len(citas)),
        "cancelo": Counter({"paciente": "Paciente", "equipo": "Equipo", "sistema": "Sin pago a tiempo"}.get(c.cancelada_por, "Sin dato") for c in canceladas).most_common(),
        "motivos": Counter(c.motivo_cancelacion or "Sin motivo" for c in canceladas).most_common(6),
        "anticipacion": [(k, anticipacion[k]) for k in ("Menos de 24 h", "24 a 72 h", "Más de 72 h", "Sin dato") if anticipacion[k]],
        "reagendadas": sum(1 for c in citas if c.reagendada),
        "web": sum(1 for c in activas if c.origen == "web"),
        "pct_web": _pct(sum(1 for c in activas if c.origen == "web"), len(activas)),
        "ocupacion": _pct(minutos_ocupados, disponibles),
        "cobrado": sum(p.monto for p in pagos),
        "valor_atendido": sum(c.precio for c in activas if c.estado != "no_asistio"),
        "por_cobrar": sum(c.saldo for c in pasadas if c.estado not in ("no_asistio",)),
        "pacientes": len(pacientes_ids),
        "pacientes_nuevos": nuevos,
        "serie": serie,
        "por_prof": sorted(por_prof.values(), key=lambda f: -f["citas"]),
        "por_servicio": por_servicio.most_common(8),
        "por_categoria": por_categoria.most_common(),
        "por_sucursal": por_sucursal.most_common(),
    }


def citas_y_pagos(desde, hasta, profesional_ids=None, sucursal_id=None, categoria=None):
    q = Cita.query.filter(Cita.inicio >= datetime.combine(desde, time()),
                          Cita.inicio < datetime.combine(hasta + timedelta(days=1), time()))
    qp = Pago.query.filter(Pago.fecha >= desde, Pago.fecha <= hasta)
    if profesional_ids is not None:
        q = q.filter(Cita.profesional_id.in_(profesional_ids or [0]))
        qp = qp.filter(Pago.profesional_id.in_(profesional_ids or [0]))
    citas = q.all()
    if sucursal_id:
        citas = [c for c in citas if c.sucursal_id == sucursal_id]
    if categoria:
        citas = [c for c in citas if (c.servicio.categoria or "") == categoria]
    pagos = qp.all()
    if sucursal_id or categoria:
        ids = {c.id for c in citas}
        pagos = [p for p in pagos if p.cita_id in ids]
    return citas, pagos
