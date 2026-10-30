from datetime import date, datetime

import pytest

from app import ajustes, tiempo
from app.disponibilidad import calcular
from app.extensions import db
from app.models import Bloqueo, Cita, Paciente, Tarifa
from app.precios import precio_para
from app.reservas import ReservaError, cancelable, copiar, liberar_horas_sin_pagar, reagendar, reservar, rut_valido

BASE = {"fecha": "2026-11-03", "hora": "09:45", "nombre": "Carla Soto", "email": "carla@ejemplo.cl",
        "telefono": "+56911112222", "rut": "12.345.678-5"}


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


def test_equipo_sin_anticipacion(datos):
    r = calcular(datos["consulta"], [datos["ana"]], date(2026, 11, 2), date(2026, 11, 2), equipo=True)
    assert "09:00" in r[date(2026, 11, 2)]


def test_modalidad_y_sucursal_por_tramo(datos):
    d = date(2026, 11, 2)
    # Beto: lunes presencial en Ñuñoa, martes sólo online.
    assert "15:00" in calcular(datos["consulta"], [datos["beto"]], d, d)[d]
    assert calcular(datos["online"], [datos["beto"]], d, d) == {}
    assert "15:00" in calcular(datos["online"], [datos["beto"]], date(2026, 11, 3), date(2026, 11, 3))[date(2026, 11, 3)]
    assert calcular(datos["consulta"], [datos["beto"]], d, d, sucursal_id=datos["centro"].id) == {}
    c = reservar(datos_cita(datos, profesional_id=0, fecha="2026-11-02", hora="15:00", sucursal_id=datos["nunoa"].id))
    assert c.profesional_id == datos["beto"].id and c.sucursal_id == datos["nunoa"].id and c.modalidad == "presencial"


def test_servicio_presencial_u_online(datos):
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, servicio_id=datos["ambas"].id, hora="09:00"))  # falta elegir
    c = reservar(datos_cita(datos, servicio_id=datos["ambas"].id, hora="09:00", modalidad="online"))
    assert c.online and c.sucursal_id is None


def test_especialidad_filtra(datos):
    d = date(2026, 11, 2)
    r = calcular(datos["consulta"], [datos["ana"], datos["beto"]], d, d, especialidad_id=datos["prenatal"].id)
    assert "15:00" not in r.get(d, {})  # Beto no atiende prenatal


def test_precios_especiales(datos):
    s = datos["ambas"]
    db.session.add_all([
        Tarifa(servicio=s, modalidad="online", precio=30000),
        Tarifa(servicio=s, especialidad_id=datos["prenatal"].id, precio=40000),
        Tarifa(servicio=s, modalidad="online", especialidad_id=datos["prenatal"].id, precio=38000),
    ])
    db.session.commit()
    assert precio_para(s, "presencial") == 35000
    assert precio_para(s, "online") == 30000
    assert precio_para(s, "presencial", especialidad_id=datos["prenatal"].id) == 40000
    assert precio_para(s, "online", especialidad_id=datos["prenatal"].id) == 38000
    c = reservar(datos_cita(datos, servicio_id=s.id, hora="09:00", modalidad="online", especialidad_id=datos["prenatal"].id))
    assert c.precio == 38000 and c.estado_pago == "por_cobrar"


def test_no_se_toma_dos_veces_y_crea_paciente(datos):
    c = reservar(datos_cita(datos))
    assert c.fin == datetime(2026, 11, 3, 10, 30) and c.rut == "12.345.678-5" and c.precio == 25000
    assert c.paciente.rut == "12.345.678-5"
    with pytest.raises(ReservaError) as e:
        reservar(datos_cita(datos))
    assert e.value.codigo == "no_disponible"
    otra = reservar(datos_cita(datos, hora="11:15", nombre="Carla S."))
    assert otra.paciente_id == c.paciente_id and Paciente.query.count() == 1
    hijo = reservar(datos_cita(datos, hora="12:00", nombre="Tomás Soto", rut="7.654.321-6"))  # mismo correo, otro RUT
    assert hijo.paciente_id != c.paciente_id


def test_validaciones(datos):
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, rut="12.345.678-9"))
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, hora="09:50"))
    with pytest.raises(ReservaError):
        reservar(datos_cita(datos, email="no-es-correo"))
    assert rut_valido("7.654.321-6") and rut_valido("11111111-1") and not rut_valido("11111111-2")


def test_panel_permite_sobrecupo_pero_no_choques(datos):
    c = reservar(datos_cita(datos, hora="18:00", rut=""), desde_panel=True)
    assert c.origen == "panel"
    with pytest.raises(ReservaError) as e:
        reservar(datos_cita(datos, hora="18:30", rut=""), desde_panel=True)
    assert e.value.codigo == "choque"


def test_reagendar_y_copiar(datos):
    c = reservar(datos_cita(datos))
    otra = reservar(datos_cita(datos, hora="11:15", email="otra@ejemplo.cl"))
    with pytest.raises(ReservaError):
        reagendar(c, "2026-11-03", "11:00")  # se topa con la otra
    reagendar(c, "2026-11-04", "10:00")
    assert c.inicio == datetime(2026, 11, 4, 10, 0) and c.fin == datetime(2026, 11, 4, 10, 45) and c.reagendada == 1
    creadas, saltadas = copiar(otra, "2026-11-10", "11:15", semanas=3)
    assert [x.inicio.date() for x in creadas] == [date(2026, 11, 10), date(2026, 11, 17), date(2026, 11, 24)]
    assert all(x.paciente_id == otra.paciente_id and x.precio == otra.precio for x in creadas)
    creadas, saltadas = copiar(otra, "2026-11-10", "11:15")
    assert creadas == [] and saltadas == [datetime(2026, 11, 10, 11, 15)]


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
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["webpay"], "pago_porcentaje": 40, "pago_minutos": 20})
    c = reservar(datos_cita(datos, fecha="2026-11-05", hora="09:00"))
    assert (c.estado, c.estado_pago, c.monto) == ("pendiente", "pendiente", 10000)
    assert c.expira == datetime(2026, 11, 2, 8, 20)
    tiempo.fijar_reloj(datetime(2026, 11, 2, 8, 21))
    assert "09:00" in calcular(datos["consulta"], [datos["ana"]], date(2026, 11, 5), date(2026, 11, 5))[date(2026, 11, 5)]
    assert liberar_horas_sin_pagar() == 1
    c = db.session.get(Cita, c.id)
    assert c.estado == "cancelada" and c.cancelada_por == "sistema"
