"""Crear, reagendar, copiar, cancelar y liberar citas."""
import re
from datetime import datetime, timedelta

from sqlalchemy import func, text

from . import ajustes
from .disponibilidad import calcular, filtro_ocupa, modalidad_de, sucursal_en
from .precios import precio_para
from .extensions import db
from .models import ESTADOS, Cita, Especialidad, Paciente, Profesional, Servicio, Sucursal
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


def _inicio(fecha, hora):
    try:
        return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        raise ReservaError("Elige un día y una hora.")


def choque(profesional_id, inicio, fin, excepto_id=None):
    """La cita del profesional que se topa con ese horario, si hay una."""
    q = Cita.query.filter(Cita.profesional_id == profesional_id, Cita.inicio < fin, Cita.fin > inicio, filtro_ocupa())
    if excepto_id:
        q = q.filter(Cita.id != excepto_id)
    return q.first()


def paciente_para(nombre, rut, email, telefono):
    """Busca al paciente por RUT y, si no tiene, por correo; si no existe lo crea.
    Completa los datos que le falten."""
    p = Paciente.query.filter_by(rut=rut).first() if rut else None
    if p is None and email:
        p = Paciente.query.filter(func.lower(Paciente.email) == email.lower()).order_by(Paciente.id).first()
        # Un mismo correo puede ser de una familia: con otro RUT, es otra persona.
        if p is not None and rut and p.rut and p.rut != rut:
            p = None
    if p is None:
        p = Paciente(nombre=nombre, rut=rut, email=email, telefono=telefono, creado=ahora())
        db.session.add(p)
    else:
        p.rut = p.rut or rut
        p.email = p.email or email
        p.telefono = telefono or p.telefono
    return p


def reservar(datos, desde_panel=False):
    """Crea una cita y la guarda. Devuelve la Cita o lanza ReservaError.

    Desde la web la hora tiene que estar entre las libres. Desde el panel sólo
    se exige que no choque con otra cita del profesional (permite sobrecupos
    fuera de horario).
    """
    servicio = db.session.get(Servicio, int(datos.get("servicio_id") or 0))
    if not servicio or (not servicio.activo and not desde_panel):
        raise ReservaError("Elige un servicio.")

    inicio = _inicio(datos.get("fecha"), datos.get("hora"))
    fin = inicio + timedelta(minutes=servicio.duracion)

    paciente = None
    if desde_panel and datos.get("paciente_id"):
        paciente = db.session.get(Paciente, int(datos["paciente_id"]))
        if paciente is None:
            raise ReservaError("No encontramos a ese paciente.")
        nombre, email, telefono, rut = paciente.nombre, paciente.email, paciente.telefono, paciente.rut
    else:
        nombre = _texto(datos, "nombre")
        email = _texto(datos, "email").lower()
        telefono = _texto(datos, "telefono", 40)
        rut = _texto(datos, "rut", 20)
    notas = _texto(datos, "notas", 2000)

    if not nombre:
        raise ReservaError("Escribe el nombre.")
    if not EMAIL.match(email) and not (desde_panel and not email):
        raise ReservaError("Revisa el correo: ahí llega la confirmación.")
    if not desde_panel and not telefono:
        raise ReservaError("Escribe un teléfono de contacto.")
    if (rut or (not desde_panel and ajustes.get("pedir_rut"))) and paciente is None:
        if not rut_valido(rut):
            raise ReservaError("El RUT no es válido. Escríbelo con dígito verificador, por ejemplo 12.345.678-5.")
        rut = formatear_rut(rut)

    pedido = int(datos.get("profesional_id") or 0)
    if pedido:
        prof = db.session.get(Profesional, pedido)
        if not prof or (not prof.activo and not desde_panel):
            raise ReservaError("Elige con quién atenderse.")
        candidatos = [prof]
    elif desde_panel:
        raise ReservaError("Elige el profesional.")
    else:
        candidatos = Profesional.query.filter_by(activo=True).all()

    sucursal_pedida = int(datos.get("sucursal_id") or 0) or None
    if sucursal_pedida and not db.session.get(Sucursal, sucursal_pedida):
        raise ReservaError("Elige la sucursal.")
    especialidad_id = int(datos.get("especialidad_id") or 0) or None
    if especialidad_id and not db.session.get(Especialidad, especialidad_id):
        especialidad_id = None
    modalidad = modalidad_de(servicio, datos.get("modalidad"))
    if modalidad is None:
        raise ReservaError("Elige si la atención es presencial u online.")

    _candado()

    if desde_panel:
        otra = choque(candidatos[0].id, inicio, fin)
        if otra:
            db.session.rollback()
            raise ReservaError(f"{candidatos[0].nombre} ya tiene una cita de {otra.inicio:%H:%M} a {otra.fin:%H:%M} ese día.", "choque")
        profesional_id = candidatos[0].id
    else:
        libres = calcular(servicio, candidatos, inicio.date(), inicio.date(), sucursal_id=sucursal_pedida,
                          modalidad=modalidad, especialidad_id=especialidad_id)
        quienes = libres.get(inicio.date(), {}).get(inicio.strftime("%H:%M"))
        if not quienes:
            db.session.rollback()
            raise ReservaError("Esa hora se acaba de ocupar. Elige otra.", "no_disponible")
        profesional_id = quienes[0]

    prof = db.session.get(Profesional, profesional_id)
    sucursal_id = sucursal_en(prof, modalidad, inicio, fin, sucursal_pedida)
    if desde_panel and str(datos.get("precio", "")).strip().isdigit():
        precio = int(datos["precio"])  # el equipo puede cobrar otro valor
    else:
        precio = precio_para(servicio, modalidad, profesional_id, sucursal_id, especialidad_id)

    quiere_pagar = (not desde_panel and ajustes.pagos_activos()
                    and (ajustes.pago_obligatorio() or bool(datos.get("pagar"))))
    monto = ajustes.monto_a_pagar(precio) if quiere_pagar else 0
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

    if paciente is None:
        paciente = paciente_para(nombre, rut, email, telefono)

    cita = Cita(
        paciente=paciente,
        servicio_id=servicio.id,
        profesional_id=profesional_id,
        sucursal_id=sucursal_id,
        especialidad_id=especialidad_id,
        modalidad=modalidad,
        inicio=inicio,
        fin=fin,
        nombre=nombre,
        rut=rut,
        email=email,
        telefono=telefono,
        notas=notas,
        estado=estado,
        precio=precio,
        monto=monto,
        estado_pago="pendiente" if quiere_pagar else ("por_cobrar" if precio > 0 else "sin_costo"),
        expira=expira,
        origen="panel" if desde_panel else "web",
        creada=ahora(),
    )
    db.session.add(cita)
    db.session.commit()
    return cita


def reagendar(cita, fecha, hora, profesional_id=None):
    """Mueve la cita a otro día, hora o profesional. Conserva paciente y pagos."""
    if cita.estado == "cancelada":
        raise ReservaError("La cita está cancelada. Cópiala para darle una hora nueva.")
    inicio = _inicio(fecha, hora)
    fin = inicio + (cita.fin - cita.inicio)
    profesional_id = int(profesional_id or cita.profesional_id)
    if not db.session.get(Profesional, profesional_id):
        raise ReservaError("Elige el profesional.")
    _candado()
    otra = choque(profesional_id, inicio, fin, excepto_id=cita.id)
    if otra:
        db.session.rollback()
        raise ReservaError(f"Ese horario se topa con {otra.nombre} ({otra.inicio:%H:%M}–{otra.fin:%H:%M}).", "choque")
    cita.inicio, cita.fin, cita.profesional_id = inicio, fin, profesional_id
    cita.sucursal_id = sucursal_en(db.session.get(Profesional, profesional_id), cita.modalidad, inicio, fin, cita.sucursal_id)
    cita.recordatorio_enviado = None
    cita.reagendada += 1
    db.session.commit()
    db.session.refresh(cita)
    return cita


def copiar(cita, fecha, hora, profesional_id=None, semanas=1):
    """Crea citas nuevas iguales (paciente, servicio, duración, precio). Con
    semanas > 1 repite una vez por semana. Devuelve (creadas, saltadas)."""
    base = _inicio(fecha, hora)
    duracion = cita.fin - cita.inicio
    profesional_id = int(profesional_id or cita.profesional_id)
    prof = db.session.get(Profesional, profesional_id)
    if not prof:
        raise ReservaError("Elige el profesional.")
    semanas = max(1, min(52, int(semanas or 1)))
    creadas, saltadas = [], []
    _candado()
    for i in range(semanas):
        inicio = base + timedelta(weeks=i)
        fin = inicio + duracion
        if choque(profesional_id, inicio, fin):
            saltadas.append(inicio)
            continue
        nueva = Cita(
            paciente_id=cita.paciente_id, servicio_id=cita.servicio_id, profesional_id=profesional_id,
            sucursal_id=sucursal_en(prof, cita.modalidad, inicio, fin, cita.sucursal_id),
            modalidad=cita.modalidad, especialidad_id=cita.especialidad_id,
            inicio=inicio, fin=fin, nombre=cita.nombre, rut=cita.rut, email=cita.email, telefono=cita.telefono,
            estado="confirmada", precio=cita.precio,
            estado_pago="por_cobrar" if cita.precio > 0 else "sin_costo", origen="panel", creada=ahora(),
        )
        db.session.add(nueva)
        creadas.append(nueva)
    db.session.commit()
    return creadas, saltadas


def cancelable(cita):
    """¿Puede el paciente cancelar todavía desde su enlace?"""
    if cita.estado not in ("pendiente", "confirmada"):
        return False
    return ahora() <= cita.inicio - timedelta(hours=int(ajustes.get("horas_cancelar")))


def liberar_horas_sin_pagar():
    """Cancela las citas cuyo pago obligatorio no llegó a tiempo."""
    n = Cita.query.filter(
        Cita.estado_pago == "pendiente", Cita.expira.isnot(None), Cita.expira < ahora(), Cita.estado != "cancelada"
    ).update({"estado": "cancelada", "estado_pago": "vencido", "cancelada_en": ahora(), "cancelada_por": "sistema",
              "motivo_cancelacion": "No se pagó a tiempo"}, synchronize_session=False)
    if n:
        db.session.commit()
    return n
