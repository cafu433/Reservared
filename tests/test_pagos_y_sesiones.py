from datetime import datetime

from app import ajustes, pagos, sesiones, tiempo
from app.extensions import db
from app.models import Cita
from app.reservas import reservar
from conftest import Respuesta, correos


def _cita(d, **cambios):
    base = {"servicio_id": d["consulta"].id, "profesional_id": d["ana"].id, "fecha": "2026-11-03", "hora": "12:00",
            "nombre": "Carla Soto", "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}
    base.update(cambios)
    return reservar(base)


def _pago(c, monto, estado="approved"):
    return {"status": estado, "external_reference": f"rr-{c.id}-{c.token}", "currency_id": "CLP", "transaction_amount": monto}


def test_cobro_y_confirmacion(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"pago_modo": "obligatorio", "pago_porcentaje": 40})
    c = _cita(datos)
    pedidos = []

    def falso(metodo, url, json=None, **kw):
        pedidos.append((metodo, url, json))
        if url.endswith("/checkout/preferences"):
            return Respuesta(201, {"init_point": "https://www.mercadopago.cl/checkout?pref=1"})
        return Respuesta(200, respuesta_pago[0])

    monkeypatch.setattr(pagos.requests, "request", falso)
    assert pagos.url_de_pago(c) == "https://www.mercadopago.cl/checkout?pref=1"
    pref = pedidos[0][2]
    assert pref["items"][0]["unit_price"] == 10000 and pref["items"][0]["currency_id"] == "CLP"
    assert pref["external_reference"] == f"rr-{c.id}-{c.token}"
    assert pref["notification_url"] == "https://reservared.test/webhooks/mercadopago"
    assert pref["expiration_date_to"].startswith("2026-11-02T08:20:00.000-03:00")

    respuesta_pago = [_pago(c, 5000)]
    assert pagos.verificar("99") is None  # menos del monto
    assert db.session.get(Cita, c.id).estado_pago == "pendiente"

    respuesta_pago[0] = _pago(c, 10000)
    p = pagos.verificar("100")
    assert (p.estado, p.estado_pago, p.expira, p.pago_ref) == ("confirmada", "pagado", None, "100")
    assert len(correos(app)) == 2  # paciente + equipo
    pagos.verificar("100")
    assert len(correos(app)) == 2  # el aviso repetido no duplica correos


def test_pago_tardio_no_pisa_otra_reserva(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"pago_modo": "obligatorio"})
    c = _cita(datos)
    tiempo.fijar_reloj(datetime(2026, 11, 2, 8, 30))
    otra = _cita(datos, email="otro@ejemplo.cl")
    assert otra.id != c.id
    monkeypatch.setattr(pagos.requests, "request", lambda *a, **k: Respuesta(200, _pago(c, 25000)))
    p = pagos.verificar("200")
    assert (p.estado, p.estado_pago) == ("cancelada", "pagado")
    assert "ya liberada" in correos(app)[-1]["asunto"]


def test_webhook(cliente, app, datos, monkeypatch):
    ajustes.guardar({"pago_modo": "opcional"})
    c = _cita(datos, pagar=True)
    assert c.estado_pago == "pendiente" and c.expira is None
    monkeypatch.setattr(pagos.requests, "request", lambda *a, **k: Respuesta(200, _pago(c, 25000)))
    r = cliente.post("/webhooks/mercadopago?type=payment&data.id=321", json={"type": "payment", "data": {"id": "321"}})
    assert r.status_code == 200
    assert db.session.get(Cita, c.id).estado_pago == "pagado"


def test_meet_con_google(app, datos, monkeypatch):
    ajustes.guardar({"google_refresh_token": "rt"})
    enviado = {}

    def post(url, **kw):
        if url == sesiones.TOKEN:
            return Respuesta(200, {"access_token": "at", "expires_in": 3600})
        enviado.update(kw)
        return Respuesta(200, {"id": "evento1", "hangoutLink": "https://meet.google.com/abc-defg-hij"})

    borrados = []
    monkeypatch.setattr(sesiones.requests, "post", post)
    monkeypatch.setattr(sesiones.requests, "delete", lambda url, **kw: borrados.append(url) or Respuesta(204, {}))
    c = _cita(datos, servicio_id=datos["online"].id, hora="09:00")
    sesiones.asegurar(c)
    assert c.enlace_sesion == "https://meet.google.com/abc-defg-hij" and c.google_evento_id == "evento1"
    ev = enviado["json"]
    assert ev["start"]["dateTime"] == "2026-11-03T09:00:00-03:00"
    assert {a["email"] for a in ev["attendees"]} == {"carla@ejemplo.cl", "ana@ejemplo.cl"}
    assert enviado["params"]["conferenceDataVersion"] == 1
    sesiones.cancelar(c)
    assert borrados and c.enlace_sesion == ""


def test_sala_fija_sin_google(app, datos):
    datos["ana"].enlace_sala = "https://zoom.us/j/123"
    db.session.commit()
    c = _cita(datos, servicio_id=datos["online"].id, hora="09:00")
    sesiones.asegurar(c)
    assert c.enlace_sesion == "https://zoom.us/j/123"


def test_presencial_no_crea_enlace(app, datos):
    datos["ana"].enlace_sala = "https://zoom.us/j/123"
    db.session.commit()
    c = _cita(datos)
    sesiones.asegurar(c)
    assert c.enlace_sesion == ""
