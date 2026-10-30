"""Módulo Agenda: vista semanal y vista del día con una columna por
profesional. Las citas se arrastran para moverlas o copiarlas."""
from datetime import datetime, time, timedelta

from flask import render_template, request
from flask_login import current_user
from sqlalchemy import or_

from ..models import Bloqueo, Cita
from ..permisos import requiere
from ..reservas import liberar_horas_sin_pagar
from ..tiempo import DIAS, MESES, ahora, dia_largo
from . import bp
from .comun import fecha, profesionales_visibles, sucursales

ALTO_HORA = 56  # px


def _minutos(t):
    return t.hour * 60 + t.minute


def _grilla(columnas, profesionales):
    """Calcula la posición de cada cita y bloqueo. Cada columna trae:
    dia, profesionales (ids), titulo. Devuelve columnas listas para pintar y el
    rango de horas."""
    tramos = [h for p in profesionales for h in p.horarios]
    h0 = min((_minutos(h.inicio) for h in tramos), default=9 * 60)
    h1 = max((_minutos(h.fin) for h in tramos), default=19 * 60)
    for col in columnas:
        for c in col["citas"]:
            h0 = min(h0, _minutos(c.inicio))
            h1 = max(h1, _minutos(c.fin) if c.fin.date() == c.inicio.date() else 24 * 60)
    h0, h1 = (h0 // 60) * 60, min(24 * 60, -(-h1 // 60) * 60)
    total = max(60, h1 - h0)

    def posicion(a, b):
        ma = max(h0, _minutos(a))
        mb = min(h1, _minutos(b) if b.date() == a.date() else 24 * 60)
        return {"top": round((ma - h0) / total * 100, 3), "alto": round(max(mb - ma, 10) / total * 100, 3)}

    for col in columnas:
        d = col["dia"]
        carriles, bloques = [], []
        for c in sorted(col["citas"], key=lambda c: c.inicio):
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
        col["bloques"] = bloques
        grises = []
        for b in col["bloqueos"]:
            a = max(b.inicio, datetime.combine(d, time()) + timedelta(minutes=h0))
            z = min(b.fin, datetime.combine(d, time()) + timedelta(minutes=h1))
            if a < z:
                grises.append({"motivo": b.motivo, **posicion(a, z)})
        col["grises"] = grises
    return h0, h1, total


@bp.get("/agenda")
@requiere("agenda")
def agenda():
    liberar_horas_sin_pagar()
    hoy = ahora().date()
    vista = "dia" if request.args.get("vista") == "dia" else "semana"
    base = fecha(request.args.get("fecha"), hoy)
    visibles = profesionales_visibles(solo_activos=True)
    elegido = request.args.get("profesional", type=int) if current_user.ve_todo else current_user.profesional_id
    sucursal = request.args.get("sucursal", type=int) or None
    mostrados = [p for p in visibles if (not elegido or p.id == elegido)
                 and (not sucursal or any(h.sucursal_id in (None, sucursal) for h in p.horarios))]
    ids = [p.id for p in mostrados] or [0]

    if vista == "semana":
        lunes = base - timedelta(days=base.weekday())
        dias = [lunes + timedelta(days=i) for i in range(7)]
        anterior, siguiente = lunes - timedelta(days=7), lunes + timedelta(days=7)
        z = dias[-1]
        rango = (f"{lunes.day} – {z.day} de {MESES[z.month - 1]} {z.year}" if lunes.month == z.month else
                 f"{lunes.day} de {MESES[lunes.month - 1]} – {z.day} de {MESES[z.month - 1]} {z.year}")
    else:
        dias = [base]
        anterior, siguiente = base - timedelta(days=1), base + timedelta(days=1)
        rango = dia_largo(base).capitalize() + f" de {base.year}"

    ini = datetime.combine(dias[0], time())
    fin = datetime.combine(dias[-1] + timedelta(days=1), time())
    q = Cita.query.filter(Cita.profesional_id.in_(ids), Cita.inicio >= ini, Cita.inicio < fin, Cita.estado != "cancelada")
    if sucursal:
        q = q.filter(or_(Cita.sucursal_id == sucursal, Cita.modalidad == "online"))
    citas = q.order_by(Cita.inicio).all()
    bloqueos = Bloqueo.query.filter(
        or_(Bloqueo.profesional_id.is_(None), Bloqueo.profesional_id.in_(ids)), Bloqueo.inicio < fin, Bloqueo.fin > ini
    ).all()

    if vista == "semana":
        columnas = [{
            "dia": d, "titulo": DIAS[d.weekday()][:3].capitalize(), "numero": d.day, "hoy": d == hoy, "profesional": elegido,
            "citas": [c for c in citas if c.inicio.date() == d],
            "bloqueos": [b for b in bloqueos if b.profesional_id is None or len(mostrados) == 1 and b.profesional_id == mostrados[0].id],
        } for d in dias]
    else:
        columnas = [{
            "dia": base, "titulo": p.nombre, "numero": None, "hoy": base == hoy, "profesional": p.id,
            "citas": [c for c in citas if c.profesional_id == p.id],
            "bloqueos": [b for b in bloqueos if b.profesional_id in (None, p.id)],
        } for p in mostrados]

    h0, h1, total = _grilla(columnas, mostrados)
    linea_ahora = None
    if hoy in dias:
        m = _minutos(ahora())
        if h0 <= m <= h1:
            linea_ahora = round((m - h0) / total * 100, 3)

    return render_template(
        "panel/agenda.html",
        vista=vista, columnas=columnas, horas=list(range(h0 // 60, h1 // 60)), alto_hora=ALTO_HORA, h0=h0,
        base=base, anterior=anterior, siguiente=siguiente, hoy=hoy, rango=rango,
        visibles=visibles, elegido=elegido, sucursal=sucursal, sucursales=sucursales(),
        linea_ahora=linea_ahora, total_citas=len(citas),
    )
