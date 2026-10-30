"""Cuánto vale una cita: el precio base del servicio o la tarifa especial que
mejor calce (modalidad, especialidad, profesional, sucursal)."""


def precio_para(servicio, modalidad=None, profesional_id=None, sucursal_id=None, especialidad_id=None):
    mejor, puntos_mejor = servicio.precio, -1
    for t in servicio.tarifas:
        condiciones = [
            (t.modalidad, modalidad),
            (t.especialidad_id, especialidad_id),
            (t.profesional_id, profesional_id),
            (t.sucursal_id, sucursal_id),
        ]
        if any(regla and regla != valor for regla, valor in condiciones):
            continue
        puntos = sum(1 for regla, _ in condiciones if regla)
        if puntos > puntos_mejor:
            mejor, puntos_mejor = t.precio, puntos
    return mejor


def rango(servicio):
    """Precio más bajo y más alto posibles, para mostrar 'desde $…'."""
    precios = [servicio.precio] + [t.precio for t in servicio.tarifas]
    return min(precios), max(precios)
