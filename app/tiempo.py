"""La hora de la aplicación.

Todas las fechas se guardan sin zona, en la hora de Chile. ``ahora()`` es la
única fuente de "ahora", así las pruebas pueden fijar el reloj.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Santiago"))

_reloj_fijo = None

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def ahora():
    if _reloj_fijo is not None:
        return _reloj_fijo
    return datetime.now(ZONA).replace(tzinfo=None, microsecond=0)


def fijar_reloj(dt):
    global _reloj_fijo
    _reloj_fijo = dt


def con_zona(dt):
    return dt.replace(tzinfo=ZONA)


def fecha_larga(dt):
    """'martes 3 de noviembre de 2026, 09:45'"""
    return f"{DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%H:%M}"


def dia_largo(d):
    """'martes 3 de noviembre'"""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def pesos(monto):
    return "$" + f"{int(monto or 0):,}".replace(",", ".")
