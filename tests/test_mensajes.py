from app import mensajes, sesiones
from app.extensions import db
from app.models import Cita
from app.reservas import reservar
from conftest import Respuesta, correos, entrar


def _cita(d, **cambios):
    base = {"servicio_id": d["consulta"].id, "profesional_id": d["ana"].id, "fecha": "2026-11-03", "hora": "10:30",
            "nombre": "Carla Soto", "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}
    base.update(cambios)
    return reservar(base)


def test_bloques_online_y_presencial(app, datos):
    texto = "Hola {nombre}.[online] Enlace: {enlace_sesion}[/online][presencial] Lugar: {lugar}[/presencial]"
    pres = mensajes.rellenar(texto, {"nombre": "Ana", "lugar": "Centro", "enlace_sesion": "x", "_online": False})
    onl = mensajes.rellenar(texto, {"nombre": "Ana", "lugar": "", "enlace_sesion": "https://meet/x", "_online": True})
    assert pres == "Hola Ana. Lugar: Centro" and onl == "Hola Ana. Enlace: https://meet/x"
    assert mensajes.validar("{nombre} {nombr}") == ["nombr"]


def test_confirmacion_online_lleva_el_enlace(app, datos):
    app.test_request_context().push()
    datos["beto"].enlace_sala = "https://zoom.us/j/999"
    db.session.commit()
    from app import correos as avisos
    c = _cita(datos, servicio_id=datos["online"].id, profesional_id=datos["beto"].id, hora="15:00")
    avisos.nueva_cita(c, avisar_equipo=False)
    m = correos(app)[-1]
    assert "https://zoom.us/j/999" in m["cuerpo"] and "Lugar:" not in m["cuerpo"]
    assert c.enlace_avisado == "https://zoom.us/j/999"
    assert not avisos.enlace_si_falta(c)  # ya lo tiene: no se repite


def test_confirmacion_presencial_lleva_la_direccion(app, datos):
    app.test_request_context().push()
    from app import correos as avisos
    avisos.nueva_cita(_cita(datos), avisar_equipo=False)
    m = correos(app)[-1]
    assert "Centro, Alameda 100" in m["cuerpo"] and "sesión online" not in m["cuerpo"]


def test_mensaje_personalizado_y_apagado(app, datos):
    app.test_request_context().push()
    mensajes.guardar("confirmacion", "Reserva {servicio}", "Hola {nombre_completo}, nos vemos el {fecha}.", True)
    from app import correos as avisos
    c = _cita(datos)
    avisos.nueva_cita(c, avisar_equipo=False)
    m = correos(app)[-1]
    assert m["asunto"] == "Reserva Consulta" and m["cuerpo"] == "Hola Carla Soto, nos vemos el martes 3 de noviembre."
    mensajes.guardar("confirmacion", "x", "y", False)
    antes = len(correos(app))
    avisos.nueva_cita(c, avisar_equipo=False)
    assert len(correos(app)) == antes
    mensajes.restablecer("confirmacion")
    assert mensajes.plantilla("confirmacion")["asunto"] == mensajes.PLANTILLAS["confirmacion"]["asunto"]


def test_enlace_creado_despues_se_envia_solo(cliente, app, datos, monkeypatch):
    c = _cita(datos, servicio_id=datos["online"].id, profesional_id=datos["beto"].id, hora="15:00")
    assert c.enlace_sesion == ""
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    cliente.post(f"/panel/citas/{c.id}", data={"accion": "enlace", "enlace_sesion": "https://meet.google.com/nuevo"})
    m = correos(app)[-1]
    assert m["asunto"].startswith("Tu enlace para la sesión") and "https://meet.google.com/nuevo" in m["cuerpo"]
    assert db.session.get(Cita, c.id).enlace_avisado == "https://meet.google.com/nuevo"


def test_pantallas_de_mensajes(cliente, app, datos):
    entrar(cliente, "admin@ejemplo.cl", "clave-admin")
    assert cliente.get("/panel/mensajes").status_code == 200
    pagina = cliente.get("/panel/mensajes/confirmacion").get_data(as_text=True)
    assert "meet.google.com/abc-defg-hij" in pagina and "Av. Providencia 1234" in pagina
    r = cliente.post("/panel/mensajes/confirmacion", data={"accion": "guardar", "asunto": "Hola", "cuerpo": "{nombree}", "activo": "1"})
    assert "no existen" in r.get_data(as_text=True)
    cliente.post("/panel/mensajes/confirmacion", data={"accion": "guardar", "asunto": "Hola {nombre}", "cuerpo": "Texto {fecha}", "activo": "1"})
    assert mensajes.plantilla("confirmacion")["cuerpo"] == "Texto {fecha}"
    cliente.post("/panel/mensajes/confirmacion", data={"accion": "probar", "asunto": "A {nombre}", "cuerpo": "B", "online_prueba": "1"})
    assert correos(app)[-1]["asunto"] == "[Prueba] A Camila" and correos(app)[-1]["para"] == ["admin@ejemplo.cl"]
