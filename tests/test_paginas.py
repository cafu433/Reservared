from app.extensions import db
from app.models import Cita, Profesional, Usuario
from conftest import correos, entrar


def _reserva(cliente, datos, **cambios):
    cuerpo = {"servicio_id": datos["consulta"].id, "profesional_id": datos["ana"].id, "fecha": "2026-11-03", "hora": "09:00",
              "nombre": "Carla Soto", "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}
    cuerpo.update(cambios)
    return cliente.post("/api/reservas", json=cuerpo)


def test_pagina_y_api_publicas(cliente, app, datos):
    assert cliente.get("/reservar").status_code == 200
    r = cliente.get(f"/api/disponibilidad?servicio={datos['consulta'].id}&profesional=0&desde=2026-11-01&hasta=2026-11-30")
    assert "2026-11-03" in r.get_json()["dias"]
    r = _reserva(cliente, datos)
    assert r.status_code == 200, r.get_json()
    assert len(correos(app)) == 2
    c = Cita.query.one()
    assert cliente.get(f"/cita/{c.token}").status_code == 200
    r = _reserva(cliente, datos)
    assert r.status_code == 400 and r.get_json()["code"] == "no_disponible"


def test_campo_trampa(cliente, datos):
    assert _reserva(cliente, datos, sitio_web="spam").status_code == 400
    assert Cita.query.count() == 0


def test_paciente_cancela(cliente, app, datos):
    _reserva(cliente, datos)
    c = Cita.query.one()
    r = cliente.post(f"/cita/{c.token}", data={"accion": "cancelar"})
    assert r.status_code == 302 and "r=cancelada" in r.location
    assert db.session.get(Cita, c.id).estado == "cancelada"


def test_panel_pide_entrar(cliente, datos):
    r = cliente.get("/panel/")
    assert r.status_code == 302 and "/panel/entrar" in r.location


def test_admin_ve_todo(cliente, datos):
    _reserva(cliente, datos)
    _reserva(cliente, datos, profesional_id=datos["beto"].id, fecha="2026-11-02", hora="15:00", email="otro@ejemplo.cl")
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    for ruta in ["/panel/", "/panel/?semana=2026-11-02", "/panel/citas?desde=2026-11-01&hasta=2026-11-30", "/panel/pacientes",
                 "/panel/servicios", "/panel/profesionales", f"/panel/profesionales/{datos['ana'].id}", "/panel/bloqueos",
                 "/panel/equipo", "/panel/ajustes", "/panel/citas/nueva", "/panel/cuenta"]:
        assert cliente.get(ruta).status_code == 200, ruta
    pagina = cliente.get("/panel/?semana=2026-11-02").get_data(as_text=True)
    assert "Carla Soto" in pagina and "15:00" in pagina
    c = Cita.query.first()
    assert cliente.get(f"/panel/citas/{c.id}").status_code == 200


def test_profesional_ve_solo_lo_suyo(cliente, datos):
    _reserva(cliente, datos)
    _reserva(cliente, datos, profesional_id=datos["beto"].id, fecha="2026-11-02", hora="15:00", nombre="Paciente de Beto", email="otro@ejemplo.cl")
    de_beto = Cita.query.filter_by(profesional_id=datos["beto"].id).one()
    entrar(cliente, "ana@ejemplo.cl", "clave-ana")
    pagina = cliente.get("/panel/?semana=2026-11-02").get_data(as_text=True)
    assert "Carla Soto" in pagina and "Paciente de Beto" not in pagina
    assert cliente.get(f"/panel/citas/{de_beto.id}").status_code == 404
    assert cliente.get("/panel/ajustes").status_code == 403
    assert cliente.get(f"/panel/profesionales/{datos['beto'].id}").status_code == 403
    assert cliente.get(f"/panel/profesionales/{datos['ana'].id}").status_code == 200


def test_admin_crea_profesional_con_acceso(cliente, app, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post("/panel/profesionales/nuevo", data={
        "nombre": "Carmen Díaz", "email": "carmen@ejemplo.cl", "activo": "1", "acceso": "1",
        "h-0-0-ini": "10:00", "h-0-0-fin": "14:00",
    })
    assert r.status_code == 302
    p = Profesional.query.filter_by(nombre="Carmen Díaz").one()
    assert len(p.horarios) == 1 and p.usuario and p.usuario.rol == "profesional"
    assert any("Tu acceso" in m["asunto"] for m in correos(app))


def test_horario_invalido(cliente, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post(f"/panel/profesionales/{datos['ana'].id}", data={"nombre": "Ana Rojas", "activo": "1", "h-0-0-ini": "14:00", "h-0-0-fin": "10:00"})
    assert r.status_code == 200 and "terminar después de empezar" in r.get_data(as_text=True)
    assert len(db.session.get(Profesional, datos["ana"].id).horarios) == 5


def test_cita_desde_panel_y_cambio_de_estado(cliente, app, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post("/panel/citas/nueva", data={
        "servicio_id": datos["consulta"].id, "profesional_id": datos["ana"].id, "fecha": "2026-11-03", "hora": "17:00",
        "nombre": "Por teléfono", "email": "tel@ejemplo.cl", "estado": "confirmada",
    })
    assert r.status_code == 302
    c = Cita.query.one()
    cliente.post(f"/panel/citas/{c.id}", data={"accion": "estado", "estado": "cancelada", "avisar": "1"})
    assert db.session.get(Cita, c.id).estado == "cancelada"
    assert correos(app)[-1]["asunto"].startswith("Tu hora fue cancelada")


def test_restablecer_clave(cliente, app, datos):
    cliente.post("/panel/olvide", data={"email": "ana@ejemplo.cl"})
    enlace = [l for l in correos(app)[-1]["cuerpo"].split() if "/panel/restablecer/" in l][0]
    ruta = enlace.replace("https://reservared.test", "")
    cliente.post(ruta, data={"clave": "nueva-clave-123"})
    assert Usuario.query.filter_by(email="ana@ejemplo.cl").one().revisar_clave("nueva-clave-123")
    r = cliente.post(ruta, data={"clave": "otra-clave-456"}, follow_redirects=True)
    assert "ya se usó" in r.get_data(as_text=True)
