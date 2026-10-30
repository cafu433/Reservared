from datetime import date, datetime

import pytest

from app import ajustes, tiempo
from app.disponibilidad import calcular
from app.models import Bloqueo, Cita
from app.extensions import db
from app.reservas import ReservaError, cancelable, liberar_horas_sin_pagar, reservar, rut_valido

BASE = {"servicio_id": 0, "profesional_id": 0, "fecha": "2026-11-03", "hora": "09:45", "nombre": "Carla Soto",
        "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}


def datos_cita(d, **cambios):
    base = dict(BASE, servicio_id=d["consulta"].id, profesional_id=d["ana"].id)
    base.update(cambios)
    return base


def test_horas_libres(datos):
    r = calcular(datos["consulta"], [datos["ana"]], date(2026, 11, 2), date(2026, 11, 8))
    assert "09:00" not in r[date(2026, 11, 2)]  # 2 h de anticipación a las 08:00
    assert "10:30" in r[date(2026, 11, 2)]
    assert list(r[date(2026, 11, 3)]) == ["09:00", "09:45", "10:30", "11:15", "12:00"]
    assert date(2026, 11, 7) not in r and date(2026, 11, 8) not in r


def test_cualquier_profesional(datos):
    r = calcular(datos["consulta"], [datos["ana"], datos["beto"]], date(2026, 11, 2), date(2026, 11, 2))
    assert r[date(2026, 11, 2)]["15:00"] == [datos["beto"].id]
    c = reservar(datos_cita(datos, profesional_id=0, fecha="2026-11-02", hora="15:00"))
    assert c.profesional_id == datos["beto"].id


def test_servicios_por_profesional(datos):
    datos["beto"].servicios = [datos["online"]]
    db.session.commit()
    r = calcular(datos["consulta"], [datos["ana"], datos["beto"]], date(2026, 11, 2), date(2026, 11, 2))
    assert "15:00" not in r.get(date(2026, 11, 2), {})


def test_no_se_toma_dos_veces(datos):
    c = reservar(datos_cita(datos))
    assert c.fin == datetime(2026, 11, 3, 10, 30)
    assert c.rut == "12.345.678-5"
    with pytest.raises(ReservaError) as e:
        reservar(datos_cita(datos))
    assert e.value.codigo == "no_disponible"
    r = calcular(datos["consulta"], [datos["ana"]], date(2026, 11, 3), date(2026, 11, 3))
    assert "09:45" not in r[date(2026, 11, 3)] and "09:00" in r[date(2026, 11, 3)]


def test_validaciones(datos):
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, rut="12.345.678-9"))
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, hora="09:50"))  # fuera de la grilla
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, email="no-es-correo"))
    assert rut_valido("7.654.321-6") and rut_valido("11111111-1") and not rut_valido("11111111-2")


def test_panel_permite_fuera_de_horario_pero_no_choques(datos):
    c = reservar(datos_cita(datos, hora="18:00", rut=""), desde_panel=True)
    assert c.origen == "panel"
    with pytest.raises(ReservaError) as e:
        reservar(datos_cita(datos, hora="18:30", rut=""), desde_panel=True)
    assert e.value.codigo == "choque"


def test_bloqueo_de_todo_el_equipo(datos):
    db.session.add(Bloqueo(inicio=datetime(2026, 11, 4), fin=datetime(2026, 11, 4, 23, 59), motivo="Feriado"))
    db.session.commit()
    assert calcular(datos["consulta"], [datos["ana"], datos["beto"]], date(2026, 11, 4), date(2026, 11, 4)) == {}


def test_plazo_para_cancelar(datos):
    c = reservar(datos_cita(datos))
    assert cancelable(c)
    tiempo.fijar_reloj(datetime(2026, 11, 2, 12, 0))
    assert not cancelable(c)


def test_pago_obligatorio_guarda_la_hora_y_la_libera(app, datos):
    app.config["MP_ACCESS_TOKEN"] = "TEST"
    ajustes.guardar({"pago_modo": "obligatorio", "pago_porcentaje": 40, "pago_minutos": 20})
    c = reservar(datos_cita(datos, fecha="2026-11-05", hora="09:00"))
    assert (c.estado, c.estado_pago, c.monto) == ("pendiente", "pendiente", 10000)
    assert c.expira == datetime(2026, 11, 2, 8, 20)
    tiempo.fijar_reloj(datetime(2026, 11, 2, 8, 21))
    r = calcular(datos["consulta"], [datos["ana"]], date(2026, 11, 5), date(2026, 11, 5))
    assert "09:00" in r[date(2026, 11, 5)]
    assert liberar_horas_sin_pagar() == 1
    assert db.session.get(Cita, c.id).estado == "cancelada"
