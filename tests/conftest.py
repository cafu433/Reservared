from datetime import datetime, time

import pytest

from app import create_app, tiempo
from app.config import ConfigPruebas
from app.extensions import db
from app.models import Horario, Profesional, Servicio, Usuario

# Lunes 2 de noviembre de 2026, 08:00 en Chile.
AHORA = datetime(2026, 11, 2, 8, 0)


@pytest.fixture
def app():
    tiempo.fijar_reloj(AHORA)
    app = create_app(ConfigPruebas)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    tiempo.fijar_reloj(None)


@pytest.fixture
def cliente(app):
    return app.test_client()


@pytest.fixture
def datos(app):
    consulta = Servicio(nombre="Consulta", duracion=45, precio=25000)
    online = Servicio(nombre="Sesión online", duracion=50, precio=30000, modalidad="online")
    ana = Profesional(nombre="Ana Rojas", email="ana@ejemplo.cl", titulo="Psicóloga")
    beto = Profesional(nombre="Beto Muñoz", email="beto@ejemplo.cl")
    db.session.add_all([consulta, online, ana, beto])
    db.session.flush()
    for dia in range(5):
        db.session.add(Horario(profesional_id=ana.id, dia=dia, inicio=time(9), fin=time(13)))
    db.session.add(Horario(profesional_id=beto.id, dia=0, inicio=time(15), fin=time(17)))
    admin = Usuario(email="admin@ejemplo.cl", nombre="Admin", rol="admin")
    admin.poner_clave("clave-admin")
    usuaria_ana = Usuario(email="ana@ejemplo.cl", nombre="Ana Rojas", rol="profesional", profesional_id=ana.id)
    usuaria_ana.poner_clave("clave-ana")
    db.session.add_all([admin, usuaria_ana])
    db.session.commit()
    return {"consulta": consulta, "online": online, "ana": ana, "beto": beto}


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
