from datetime import datetime, time

import pytest

from app import create_app, tiempo
from app.config import ConfigPruebas
from app.extensions import db
from app.models import Especialidad, Horario, Profesional, Servicio, Sucursal, Usuario
from app.permisos import PERFILES

# Lunes 2 de noviembre de 2026, 08:00 en Chile.
AHORA = datetime(2026, 11, 2, 8, 0)


@pytest.fixture
def app():
    tiempo.fijar_reloj(AHORA)
    from app.publico import routes as publico
    publico._intentos.clear()
    app = create_app(ConfigPruebas)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    tiempo.fijar_reloj(None)


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """Ninguna prueba sale a internet: WhatsApp responde 'ok' por defecto."""
    from app import whatsapp
    monkeypatch.setattr(whatsapp.requests, "post", lambda *a, **k: Respuesta(200, {}))


@pytest.fixture
def cliente(app):
    return app.test_client()


@pytest.fixture
def datos(app):
    centro = Sucursal(nombre="Centro", direccion="Alameda 100")
    nunoa = Sucursal(nombre="Ñuñoa", direccion="Irarrázaval 200")
    prenatal = Especialidad(nombre="Psicología prenatal")
    consulta = Servicio(nombre="Consulta", categoria="Psicología", duracion=45, precio=25000)
    online = Servicio(nombre="Sesión online", categoria="Psicología", duracion=50, precio=30000, modalidad="online")
    ambas = Servicio(nombre="Psicoterapia", categoria="Psicología", duracion=50, precio=35000, modalidad="ambas")
    ana = Profesional(nombre="Ana Rojas", email="ana@ejemplo.cl", titulo="Psicóloga", especialidades=[prenatal])
    beto = Profesional(nombre="Beto Muñoz", email="beto@ejemplo.cl")
    db.session.add_all([centro, nunoa, prenatal, consulta, online, ambas, ana, beto])
    db.session.flush()
    for dia in range(5):
        db.session.add(Horario(profesional_id=ana.id, dia=dia, inicio=time(9), fin=time(13), modalidad="ambas", sucursal_id=centro.id))
    db.session.add(Horario(profesional_id=beto.id, dia=0, inicio=time(15), fin=time(17), modalidad="presencial", sucursal_id=nunoa.id))
    db.session.add(Horario(profesional_id=beto.id, dia=1, inicio=time(15), fin=time(17), modalidad="online"))
    admin = Usuario(email="admin@ejemplo.cl", nombre="Admin", rol="admin")
    admin.poner_clave("clave-admin")
    usuaria_ana = Usuario(email="ana@ejemplo.cl", nombre="Ana Rojas", rol="profesional", profesional_id=ana.id)
    usuaria_ana.poner_permisos(PERFILES["profesional"][1])
    usuaria_ana.poner_clave("clave-ana")
    recepcion = Usuario(email="recepcion@ejemplo.cl", nombre="Recepción", rol="recepcion")
    recepcion.poner_permisos(PERFILES["recepcion"][1])
    recepcion.poner_clave("clave-recepcion")
    db.session.add_all([admin, usuaria_ana, recepcion])
    db.session.commit()
    return {"consulta": consulta, "online": online, "ambas": ambas, "ana": ana, "beto": beto,
            "centro": centro, "nunoa": nunoa, "prenatal": prenatal}


def entrar(cliente, email, clave):
    return cliente.post("/panel/entrar", data={"email": email, "clave": clave}, follow_redirects=True)


def correos(app):
    return app.extensions.setdefault("correos_enviados", [])


class Respuesta:
    def __init__(self, codigo, datos):
        self.status_code = codigo
        self._datos = datos
        self.content = b"x"

    def json(self):
        return self._datos
