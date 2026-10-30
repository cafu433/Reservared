from app import ajustes
from app.extensions import db
from app.models import Cita, Evolucion, Paciente, Profesional, Usuario
from conftest import correos, entrar


def _reserva(cliente, datos, **cambios):
    cuerpo = {"servicio_id": datos["consulta"].id, "profesional_id": datos["ana"].id, "fecha": "2026-11-03", "hora": "09:00",
              "nombre": "Carla Soto", "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}
    cuerpo.update(cambios)
    return cliente.post("/api/reservas", json=cuerpo)


def test_pagina_y_api_publicas(cliente, app, datos):
    pagina = cliente.get("/reservar").get_data(as_text=True)
    assert "prenatal" in pagina and "Centro" in pagina and "Alameda 100" in pagina
    r = cliente.get(f"/api/disponibilidad?servicio={datos['consulta'].id}&profesional=0&desde=2026-11-01&hasta=2026-11-30&sucursal={datos['centro'].id}")
    assert "2026-11-03" in r.get_json()["dias"]
    r = _reserva(cliente, datos)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["cita"]["lugar"] == "Centro, Alameda 100"
    assert len(correos(app)) == 2 and "Alameda 100" in correos(app)[0]["cuerpo"]
    c = Cita.query.one()
    assert cliente.get(f"/cita/{c.token}").status_code == 200
    assert _reserva(cliente, datos).get_json()["code"] == "no_disponible"


def test_reserva_con_pago_webpay(cliente, app, datos):
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["webpay"]})
    r = _reserva(cliente, datos, pasarela="webpay").get_json()
    c = Cita.query.one()
    assert r["pago_url"] == f"/cita/{c.token}/pagar?pasarela=webpay" and correos(app) == []


def test_campo_trampa(cliente, datos):
    assert _reserva(cliente, datos, sitio_web="spam").status_code == 400
    assert Cita.query.count() == 0


def test_paciente_cancela_con_motivo(cliente, app, datos):
    _reserva(cliente, datos)
    c = Cita.query.one()
    r = cliente.post(f"/cita/{c.token}", data={"accion": "cancelar", "motivo": "Enfermedad"})
    assert r.status_code == 302 and "r=cancelada" in r.location
    c = db.session.get(Cita, c.id)
    assert (c.estado, c.cancelada_por, c.motivo_cancelacion) == ("cancelada", "paciente", "Enfermedad")


def test_panel_pide_entrar(cliente, datos):
    r = cliente.get("/panel/agenda")
    assert r.status_code == 302 and "/panel/entrar" in r.location


def test_admin_ve_todos_los_modulos(cliente, datos):
    _reserva(cliente, datos)
    _reserva(cliente, datos, profesional_id=datos["beto"].id, fecha="2026-11-02", hora="15:00", email="otro@ejemplo.cl", rut="7.654.321-6")
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    c = Cita.query.first()
    p = Paciente.query.first()
    assert cliente.get("/panel/").status_code == 302
    for ruta in ["/panel/dashboard", "/panel/dashboard?periodo=30", "/panel/agenda?fecha=2026-11-02",
                 "/panel/agenda?vista=dia&fecha=2026-11-02", "/panel/agendar", f"/panel/agendar?servicio={datos['ambas'].id}&modalidad=online",
                 "/panel/agendar/confirmar?fecha=2026-11-04&hora=10:00", "/panel/citas?desde=2026-11-01&hasta=2026-11-30",
                 f"/panel/citas/{c.id}", "/panel/pacientes", f"/panel/pacientes/{p.id}", "/panel/pacientes/nuevo",
                 "/panel/cobranza", "/panel/cobranza?formato=csv", "/panel/profesionales", f"/panel/profesionales/{datos['ana'].id}",
                 "/panel/profesionales/nuevo", "/panel/cuentas", "/panel/cuentas/nueva", "/panel/servicios",
                 f"/panel/servicios/{datos['ambas'].id}", "/panel/sucursales", "/panel/bloqueos", "/panel/ajustes", "/panel/cuenta"]:
        assert cliente.get(ruta).status_code == 200, ruta
    pagina = cliente.get("/panel/agenda?vista=dia&fecha=2026-11-02").get_data(as_text=True)
    assert "Beto Muñoz" in pagina and "Ana Rojas" in pagina
    # La administración no ve la ficha clínica sin el permiso.
    assert "Ficha clínica" not in cliente.get(f"/panel/pacientes/{p.id}").get_data(as_text=True)


def test_profesional_ve_solo_lo_suyo(cliente, datos):
    _reserva(cliente, datos)
    _reserva(cliente, datos, profesional_id=datos["beto"].id, fecha="2026-11-02", hora="15:00", nombre="Paciente de Beto",
             email="otro@ejemplo.cl", rut="7.654.321-6")
    de_beto = Cita.query.filter_by(profesional_id=datos["beto"].id).one()
    entrar(cliente, "ana@ejemplo.cl", "clave-ana")
    pagina = cliente.get("/panel/agenda?fecha=2026-11-02").get_data(as_text=True)
    assert "Carla Soto" in pagina and "Paciente de Beto" not in pagina
    assert cliente.get(f"/panel/citas/{de_beto.id}").status_code == 404
    assert cliente.get(f"/panel/pacientes/{de_beto.paciente_id}").status_code == 404
    for ruta in ["/panel/ajustes", "/panel/cobranza", "/panel/dashboard", "/panel/cuentas", f"/panel/profesionales/{datos['beto'].id}"]:
        assert cliente.get(ruta).status_code == 403, ruta
    assert cliente.get(f"/panel/profesionales/{datos['ana'].id}").status_code == 200


def test_recepcion_agenda_y_cobra_pero_no_ve_ficha_clinica(cliente, app, datos):
    _reserva(cliente, datos)
    c = Cita.query.one()
    db.session.add(Evolucion(paciente_id=c.paciente_id, texto="Nota clínica privada"))
    db.session.commit()
    entrar(cliente, "recepcion@ejemplo.cl", "clave-recepcion")
    assert "Nota clínica privada" not in cliente.get(f"/panel/pacientes/{c.paciente_id}").get_data(as_text=True)
    assert cliente.post(f"/panel/pacientes/{c.paciente_id}", data={"accion": "evolucion", "texto": "x"}).status_code == 403
    assert cliente.get("/panel/ajustes").status_code == 403
    cliente.post(f"/panel/citas/{c.id}", data={"accion": "pago", "monto": "25000", "medio": "transferencia"})
    assert db.session.get(Cita, c.id).estado_pago == "pagado"


def test_ficha_clinica_del_profesional(cliente, datos):
    _reserva(cliente, datos)
    c = Cita.query.one()
    entrar(cliente, "ana@ejemplo.cl", "clave-ana")
    cliente.post(f"/panel/citas/{c.id}", data={"accion": "evolucion", "texto": "Primera sesión: motivo ansiedad."})
    cliente.post(f"/panel/pacientes/{c.paciente_id}", data={"accion": "clinica", "motivo_consulta": "Ansiedad", "antecedentes": "—"})
    pagina = cliente.get(f"/panel/pacientes/{c.paciente_id}").get_data(as_text=True)
    assert "Primera sesión: motivo ansiedad." in pagina and "Ansiedad" in pagina


def test_mover_y_copiar_desde_la_agenda(cliente, app, datos):
    _reserva(cliente, datos)
    c = Cita.query.one()
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post(f"/panel/citas/{c.id}/mover", json={"fecha": "2026-11-04", "hora": "10:00", "avisar": True})
    assert r.status_code == 200
    assert db.session.get(Cita, c.id).inicio.isoformat() == "2026-11-04T10:00:00"
    assert correos(app)[-2]["asunto"].startswith("Tu hora cambió")
    r = cliente.post(f"/panel/citas/{c.id}/mover", json={"fecha": "2026-11-05", "hora": "10:00", "copiar": True})
    assert r.status_code == 200 and Cita.query.count() == 2
    r = cliente.post(f"/panel/citas/{c.id}/mover", json={"fecha": "2026-11-05", "hora": "10:15"})
    assert r.status_code == 400  # choca con la copia


def test_agendar_paciente_existente(cliente, datos):
    _reserva(cliente, datos)
    p = Paciente.query.one()
    entrar(cliente, "recepcion@ejemplo.cl", "clave-recepcion")
    assert cliente.get("/panel/pacientes/buscar?q=carla").get_json()[0]["id"] == p.id
    r = cliente.post("/panel/agendar/confirmar", data={"paciente_id": p.id, "servicio_id": datos["consulta"].id,
                                                      "profesional_id": datos["ana"].id, "fecha": "2026-11-06", "hora": "10:00",
                                                      "estado": "confirmada", "precio": "20000"})
    assert r.status_code == 302
    nueva = Cita.query.order_by(Cita.id.desc()).first()
    assert nueva.paciente_id == p.id and nueva.precio == 20000 and nueva.nombre == "Carla Soto"


def test_cuentas_y_permisos(cliente, app, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post("/panel/cuentas/nueva", data={"nombre": "Paula", "email": "paula@ejemplo.cl", "rol": "personalizado",
                                                  "permisos": ["agenda", "pacientes"], "activo": "1"})
    assert r.status_code == 302
    u = Usuario.query.filter_by(email="paula@ejemplo.cl").one()
    assert u.lista_permisos == {"agenda", "pacientes"} and not u.puede("cobranza")
    assert any("Tu acceso" in m["asunto"] for m in correos(app))


def test_horario_con_modalidad_y_sucursal(cliente, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    r = cliente.post("/panel/profesionales/nuevo", data={
        "nombre": "Carmen Díaz", "email": "carmen@ejemplo.cl", "activo": "1", "acceso": "1",
        "especialidades": [str(datos["prenatal"].id)],
        "h-0-0-ini": "09:00", "h-0-0-fin": "13:00", "h-0-0-mod": "presencial", "h-0-0-suc": str(datos["nunoa"].id),
        "h-0-1-ini": "15:00", "h-0-1-fin": "18:00", "h-0-1-mod": "online",
    })
    assert r.status_code == 302
    p = Profesional.query.filter_by(nombre="Carmen Díaz").one()
    assert sorted((h.modalidad, h.sucursal_id) for h in p.horarios) == [("online", None), ("presencial", datos["nunoa"].id)]
    assert p.especialidades[0].nombre == "Psicología prenatal" and p.usuario.puede("ficha_clinica")


def test_restablecer_clave(cliente, app, datos):
    cliente.post("/panel/olvide", data={"email": "ana@ejemplo.cl"})
    enlace = [x for x in correos(app)[-1]["cuerpo"].split() if "/panel/restablecer/" in x][0]
    ruta = enlace.replace("https://reservared.test", "")
    cliente.post(ruta, data={"clave": "nueva-clave-123"})
    assert Usuario.query.filter_by(email="ana@ejemplo.cl").one().revisar_clave("nueva-clave-123")
    assert "ya se usó" in cliente.post(ruta, data={"clave": "otra-clave-456"}, follow_redirects=True).get_data(as_text=True)
