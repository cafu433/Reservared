"""Módulo Dashboard."""
from datetime import timedelta

from flask import render_template, request
from flask_login import current_user

from ..estadisticas import citas_y_pagos, resumen
from ..extensions import db
from ..models import Cita, Servicio
from ..permisos import requiere
from ..tiempo import MESES, ahora
from . import bp
from .comun import fecha, primeros_pasos, profesionales_visibles, sucursales

PERIODOS = {"mes": "Este mes", "mes_anterior": "Mes anterior", "7": "Últimos 7 días", "30": "Últimos 30 días",
            "90": "Últimos 90 días", "rango": "Elegir fechas"}


def _rango(periodo, hoy):
    if periodo == "mes_anterior":
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin
    if periodo in ("7", "30", "90"):
        return hoy - timedelta(days=int(periodo) - 1), hoy
    if periodo == "rango":
        desde = fecha(request.args.get("desde"), hoy.replace(day=1))
        return desde, max(desde, fecha(request.args.get("hasta"), hoy))
    inicio = hoy.replace(day=1)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return inicio, fin


@bp.get("/dashboard")
@requiere("dashboard")
def dashboard():
    hoy = ahora().date()
    periodo = request.args.get("periodo") if request.args.get("periodo") in PERIODOS else "mes"
    desde, hasta = _rango(periodo, hoy)
    visibles = profesionales_visibles(solo_activos=False)
    prof = request.args.get("profesional", type=int) if current_user.ve_todo else current_user.profesional_id
    suc = request.args.get("sucursal", type=int) or None
    categoria = request.args.get("categoria") or None
    profs = [p for p in visibles if p.activo and (not prof or p.id == prof)]
    ids = None if (current_user.ve_todo and not prof) else [p.id for p in profs]

    citas, pagos = citas_y_pagos(desde, hasta, ids, suc, categoria)
    r = resumen(citas, pagos, profs, desde, hasta, suc)
    maximo = max((d["citas"] + d["canceladas"] for d in r["serie"]), default=0)

    proximas = Cita.query.filter(Cita.inicio >= ahora(), Cita.inicio < ahora() + timedelta(hours=24),
                                 Cita.estado != "cancelada")
    if ids is not None:
        proximas = proximas.filter(Cita.profesional_id.in_(ids or [0]))
    categorias = [c for (c,) in db.session.query(Servicio.categoria).distinct() if c]

    titulo = PERIODOS[periodo]
    if periodo in ("mes", "mes_anterior"):
        titulo = f"{MESES[desde.month - 1].capitalize()} {desde.year}"
    return render_template(
        "panel/dashboard.html", r=r, periodo=periodo, periodos=PERIODOS, desde=desde, hasta=hasta, titulo=titulo,
        prof=prof, suc=suc, categoria=categoria, visibles=visibles, sucursales=sucursales(), categorias=sorted(categorias),
        maximo=maximo, proximas=proximas.order_by(Cita.inicio).limit(12).all(), hoy=hoy, pp=primeros_pasos(),
    )
