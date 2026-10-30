"""Pagos de las citas: registrar, calcular saldos y estados."""
from .extensions import db
from .models import MEDIOS_PAGO, Pago
from .tiempo import ahora


class CobroError(Exception):
    pass


def recalcular(cita):
    """Pone el estado de pago según lo pagado. No toca un pago en línea que
    todavía se está esperando (pendiente con plazo)."""
    pagado = cita.pagado
    if cita.precio <= 0:
        cita.estado_pago = "sin_costo"
    elif pagado >= cita.precio:
        cita.estado_pago = "pagado"
    elif pagado > 0:
        cita.estado_pago = "parcial"
    elif cita.estado_pago not in ("pendiente", "vencido"):
        cita.estado_pago = "por_cobrar"
    if cita.estado_pago in ("pagado", "parcial"):
        cita.expira = None


def registrar(cita, monto, medio="efectivo", fecha=None, referencia="", nota="", usuario_id=None):
    """Registra un pago (total o abono) de una cita y actualiza su estado."""
    try:
        monto = int(monto)
    except (TypeError, ValueError):
        raise CobroError("Escribe el monto en pesos, sin puntos.")
    if monto <= 0:
        raise CobroError("El monto tiene que ser mayor que cero.")
    if medio not in MEDIOS_PAGO:
        raise CobroError("Elige cómo pagó.")
    pago = Pago(
        cita=cita,
        paciente_id=cita.paciente_id,
        profesional_id=cita.profesional_id,
        monto=monto,
        medio=medio,
        fecha=fecha or ahora().date(),
        referencia=(referencia or "")[:120],
        nota=(nota or "")[:255],
        registrado_por=usuario_id,
    )
    db.session.add(pago)
    db.session.flush()
    db.session.refresh(cita)
    recalcular(cita)
    if cita.estado == "pendiente" and cita.estado_pago == "pagado":
        cita.estado = "confirmada"
    db.session.commit()
    return pago


def borrar(pago):
    cita = pago.cita
    db.session.delete(pago)
    db.session.flush()
    if cita:
        db.session.refresh(cita)
        recalcular(cita)
    db.session.commit()


def es_deuda(cita, hoy=None):
    """Una cita debe plata si ya ocurrió (o se marcó atendida), no está
    cancelada y le queda saldo."""
    hoy = hoy or ahora().date()
    if cita.estado in ("cancelada", "no_asistio") or cita.saldo <= 0:
        return False
    return cita.estado == "asistio" or cita.inicio.date() <= hoy
