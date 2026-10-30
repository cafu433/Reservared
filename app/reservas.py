"""Crear, cancelar y liberar citas."""
import re
from datetime import datetime, timedelta

from sqlalchemy import text

from . import ajustes
from .disponibilidad import calcular, filtro_ocupa
from .extensions import db
from .models import ESTADOS, Cita, Profesional, Servicio
from .tiempo import ahora

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ReservaError(Exception):
    def __init__(self, mensaje, codigo="invalida"):
        super().__init__(mensaje)
        self.codigo = codigo


def rut_valido(rut):
    r = re.sub(r"[^0-9kK]", "", rut or "").upper()
    if len(r) < 2 or not r[:-1].isdigit():
        return False
    cuerpo, dv = r[:-1], r[-1]
    suma, mult = 0, 2
    for c in reversed(cuerpo):
        suma += int(c) * mult
        mult = 2 if mult == 7 else mult + 1
    resto = 11 - suma % 11
    return {11: "0", 10: "K"}.get(resto, str(resto)) == dv


def formatear_rut(rut):
    r = re.sub(r"[^0-9kK]", "", rut).upper()
    return f"{int(r[:-1]):,}".replace(",", ".") + "-" + r[-1]


def _candado():
    """Dos personas no pueden tomar la misma hora a la vez. En Postgres, un
    candado de la transacción; SQLite ya escribe de a uno."""
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(724501)"))


def _texto(datos, clave, largo=190):
    return str(datos.get(clave) or "").strip()[:largo]


def reservar(datos, desde_panel=False):
    """Crea una cita y la guarda. Devuelve la Cita o lanza ReservaError.

    Desde la web la hora tiene que estar entre las libres. Desde el panel sólo
    se exige que no choque con otra cita del profesional.
    """
    servicio = db.session.get(Servicio, int(datos.get("servicio_id") or 0))
    if not servicio or (not servicio.activo and not desde_panel):
        raise ReservaError("Elige un servicio.")

    try:
        inicio = datetime.strptime(f"{datos.get('fecha')} {datos.get('hora')}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        raise ReservaError("Elige un día y una hora.")
    fin = inicio + timedelta(minutes=servicio.duracion)

    nombre = _texto(datos, "nombre")
    email = _texto(datos, "email").lower()
    telefono = _texto(datos, "telefono", 40)
    rut = _texto(datos, "rut", 20)
    notas = _texto(datos, "notas", 2000)
    if not nombre:
        raise ReservaError("Escribe el nombre.")
    if not EMAIL.match(email):
        raise ReservaError("Revisa el correo: ahí llega la confirmación.")
    if not desde_panel and not telefono:
        raise ReservaError("Escribe un teléfono de contacto.")
    if rut or (not desde_panel and ajustes.get("pedir_rut")):
        if not rut_valido(rut):
            raise ReservaError("El RUT no es válido. Escríbelo con dígito verificador, por ejemplo 12.345.678-5.")
        rut = formatear_rut(rut)

    pedido = int(datos.get("profesional_id") or 0)
    if pedido:
        prof = db.session.get(Profesional, pedido)
        if not prof or (not prof.activo and not desde_panel):
            raise ReservaError("Elige con quién atenderte.")
        candidatos = [prof]
    elif desde_panel:
        raise ReservaError("Elige el profesional.")
    else:
        candidatos = Profesional.query.filter_by(activo=True).all()

    _candado()

    if desde_panel:
        choque = Cita.query.filter(
            Cita.profesional_id == candidatos[0].id, Cita.inicio < fin, Cita.fin > inicio, filtro_ocupa()
        ).first()
        if choque:
            db.session.rollback()
            raise ReservaError(f"{candidatos[0].nombre} ya tiene una cita de {choque.inicio:%H:%M} a {choque.fin:%H:%M}.", "choque")
        profesional_id = candidatos[0].id
    else:
        libres = calcular(servicio, candidatos, inicio.date(), inicio.date())
        quienes = libres.get(inicio.date(), {}).get(inicio.strftime("%H:%M"))
        if not quienes:
            db.session.rollback()
            raise ReservaError("Esa hora se acaba de ocupar. Elige otra.", "no_disponible")
        profesional_id = quienes[0]

    quiere_pagar = (not desde_panel and ajustes.pagos_activos()
                    and (ajustes.pago_obligatorio() or bool(datos.get("pagar"))))
    monto = ajustes.monto_a_pagar(servicio.precio) if quiere_pagar else 0
    if monto <= 0:
        quiere_pagar = False

    if desde_panel:
        estado = datos.get("estado") if datos.get("estado") in ESTADOS else "confirmada"
    else:
        estado = ajustes.get("estado_inicial")
    expira = None
    if quiere_pagar and ajustes.pago_obligatorio():
        estado = "pendiente"
        expira = ahora() + timedelta(minutes=max(5, int(ajustes.get("pago_minutos"))))

    cita = Cita(
        servicio_id=servicio.id,
        profesional_id=profesional_id,
        inicio=inicio,
        fin=fin,
        nombre=nombre,
        rut=rut,
        email=email,
        telefono=telefono,
        notas=notas,
        estado=estado,
        monto=monto,
        estado_pago="pendiente" if quiere_pagar else "sin_pago",
        expira=expira,
        origen="panel" if desde_panel else "web",
        creada=ahora(),
    )
    db.session.add(cita)
    db.session.commit()
    return cita


def cancelable(cita):
    """¿Puede el paciente cancelar todavía desde su enlace?"""
    if cita.estado not in ("pendiente", "confirmada"):
        return False
    return ahora() <= cita.inicio - timedelta(hours=int(ajustes.get("horas_cancelar")))


def liberar_horas_sin_pagar():
    """Cancela las citas cuyo pago obligatorio no llegó a tiempo."""
    n = Cita.query.filter(
        Cita.estado_pago == "pendiente", Cita.expira.isnot(None), Cita.expira < ahora(), Cita.estado != "cancelada"
    ).update({"estado": "cancelada", "estado_pago": "vencido"}, synchronize_session=False)
    if n:
        db.session.commit()
    return n
