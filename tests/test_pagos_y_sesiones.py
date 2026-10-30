from datetime import datetime

from app import ajustes, cobros, pagos, sesiones, tiempo, webpay, whatsapp
from app.extensions import db
from app.models import Cita, Pago
from app.reservas import reservar
from conftest import Respuesta, correos


def _cita(d, **cambios):
    base = {"servicio_id": d["consulta"].id, "profesional_id": d["ana"].id, "fecha": "2026-11-03", "hora": "12:00",
            "nombre": "Carla Soto", "email": "carla@ejemplo.cl", "telefono": "+56911112222", "rut": "12.345.678-5"}
    base.update(cambios)
    return reservar(base)


def _pago_mp(c, monto, estado="approved"):
    return {"status": estado, "external_reference": f"rr-{c.id}-{c.token}", "currency_id": "CLP", "transaction_amount": monto}


def test_mercado_pago_abono_y_confirmacion(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["mercadopago"], "pago_porcentaje": 40})
    c = _cita(datos)
    pedidos, respuesta = [], [None]

    def falso(metodo, url, json=None, **kw):
        pedidos.append((metodo, url, json))
        if url.endswith("/checkout/preferences"):
            return Respuesta(201, {"init_point": "https://www.mercadopago.cl/checkout?pref=1"})
        return Respuesta(200, respuesta[0])

    monkeypatch.setattr(pagos.requests, "request", falso)
    assert pagos.url_de_pago(c) == "https://www.mercadopago.cl/checkout?pref=1"
    pref = pedidos[0][2]
    assert pref["items"][0]["unit_price"] == 10000 and pref["external_reference"] == f"rr-{c.id}-{c.token}"
    assert pref["expiration_date_to"].startswith("2026-11-02T08:20:00.000-03:00")

    respuesta[0] = _pago_mp(c, 5000)
    assert pagos.verificar("99") is None
    respuesta[0] = _pago_mp(c, 10000)
    p = pagos.verificar("100")
    assert (p.estado, p.estado_pago, p.pagado, p.saldo, p.expira) == ("confirmada", "parcial", 10000, 15000, None)
    assert len(correos(app)) == 2
    pagos.verificar("100")
    assert Pago.query.count() == 1 and len(correos(app)) == 2  # el aviso repetido no duplica


def test_webpay_completo(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["webpay"]})
    assert ajustes.pasarelas() == ["webpay"]
    c = _cita(datos)
    llamadas = []

    def falso(metodo, url, json=None, headers=None, **kw):
        llamadas.append((metodo, url, json, headers))
        if metodo == "POST":
            return Respuesta(200, {"token": "tok123", "url": "https://webpay3gint.transbank.cl/webpayserver/initTransaction"})
        orden = llamadas[0][2]["buy_order"]
        return Respuesta(200, {"status": "AUTHORIZED", "response_code": 0, "amount": 25000, "buy_order": orden,
                               "authorization_code": "1213"})

    monkeypatch.setattr(webpay.requests, "request", falso)
    url, token = webpay.iniciar(c, c.monto)
    assert token == "tok123" and llamadas[0][1].startswith("https://webpay3gint.transbank.cl")
    assert llamadas[0][3]["Tbk-Api-Key-Id"] == webpay.PRUEBA[0]
    assert llamadas[0][2]["return_url"] == "https://reservared.test/pago/webpay"
    cita, ok = webpay.confirmar("tok123")
    assert ok and cita.estado_pago == "pagado" and cita.estado == "confirmada" and cita.pagos[0].medio == "webpay"
    cita, ok = webpay.confirmar("tok123")  # repetido: no registra de nuevo
    assert ok and Pago.query.count() == 1


def test_webpay_no_se_activa_en_pruebas_por_olvido(app, datos):
    app.config["WEBPAY_AMBIENTE"] = "produccion"
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["webpay"]})
    assert ajustes.pasarelas() == [] and not ajustes.pagos_activos()


def test_webpay_rechazado(app, datos, monkeypatch):
    app.test_request_context().push()
    c = _cita(datos)
    monkeypatch.setattr(webpay.requests, "request", lambda m, u, json=None, **k: Respuesta(200, {"token": "t2", "url": "u"}) if m == "POST"
                        else Respuesta(200, {"status": "FAILED", "response_code": -1, "amount": 25000, "buy_order": "x"}))
    webpay.iniciar(c, 25000)
    cita, ok = webpay.confirmar("t2")
    assert not ok and cita.pagado == 0


def test_pago_tardio_no_pisa_otra_reserva(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"pago_modo": "obligatorio", "pasarelas": ["mercadopago"]})
    c = _cita(datos)
    tiempo.fijar_reloj(datetime(2026, 11, 2, 8, 30))
    _cita(datos, email="otro@ejemplo.cl")
    monkeypatch.setattr(pagos.requests, "request", lambda *a, **k: Respuesta(200, _pago_mp(c, 25000)))
    p = pagos.verificar("200")
    assert p.estado == "cancelada" and p.pagado == 25000
    assert "ya liberada" in correos(app)[-1]["asunto"]


def test_cobranza_abonos(app, datos):
    c = _cita(datos)
    cobros.registrar(c, 10000, "transferencia")
    assert (c.estado_pago, c.saldo) == ("parcial", 15000)
    cobros.registrar(c, 15000, "efectivo")
    assert c.estado_pago == "pagado"
    cobros.borrar(c.pagos[0])
    assert (c.estado_pago, c.saldo) == ("parcial", 10000)


def test_meet_con_google(app, datos, monkeypatch):
    app.test_request_context().push()
    ajustes.guardar({"google_refresh_token": "rt"})
    enviado, borrados = {}, []

    def post(url, **kw):
        if url == sesiones.TOKEN:
            return Respuesta(200, {"access_token": "at", "expires_in": 3600})
        enviado.update(kw)
        return Respuesta(200, {"id": "evento1", "hangoutLink": "https://meet.google.com/abc-defg-hij"})

    monkeypatch.setattr(sesiones.requests, "post", post)
    monkeypatch.setattr(sesiones.requests, "delete", lambda url, **kw: borrados.append(url) or Respuesta(204, {}))
    c = _cita(datos, servicio_id=datos["online"].id, profesional_id=datos["beto"].id, hora="15:00")
    sesiones.asegurar(c)
    assert c.enlace_sesion == "https://meet.google.com/abc-defg-hij"
    assert enviado["json"]["start"]["dateTime"] == "2026-11-03T15:00:00-03:00"
    assert {a["email"] for a in enviado["json"]["attendees"]} == {"carla@ejemplo.cl", "beto@ejemplo.cl"}
    sesiones.cancelar(c)
    assert borrados and c.enlace_sesion == ""


def test_whatsapp(app, datos, monkeypatch):
    app.test_request_context().push()
    assert whatsapp.numero("+56 9 1111 2222") == "56911112222" and whatsapp.numero("911112222") == "56911112222"
    enviados = []
    monkeypatch.setattr(whatsapp.requests, "post", lambda url, json=None, **k: enviados.append((url, json)) or Respuesta(200, {}))
    c = _cita(datos)
    from app import correos as avisos
    avisos.nueva_cita(c)
    url, cuerpo = enviados[0]
    assert url.endswith("/123/messages") and cuerpo["to"] == "56911112222"
    assert cuerpo["template"]["name"] == "confirmacion_hora"
    assert [p["text"] for p in cuerpo["template"]["components"][0]["parameters"]][0] == "Carla"
    assert "wa.me/56911112222?text=" in whatsapp.enlace_manual(c.telefono, "hola")


def test_recordatorios(cliente, app, datos, monkeypatch):
    monkeypatch.setattr(whatsapp.requests, "post", lambda *a, **k: Respuesta(200, {}))
    c = _cita(datos, hora="09:00")
    assert cliente.get("/tareas/recordatorios?clave=mala").status_code == 403
    tiempo.fijar_reloj(datetime(2026, 11, 2, 10, 0))
    r = cliente.post("/tareas/recordatorios?clave=clave-tareas")
    assert r.get_json()["enviados"] == 1 and db.session.get(Cita, c.id).recordatorio_enviado
    assert cliente.post("/tareas/recordatorios?clave=clave-tareas").get_json()["enviados"] == 0
