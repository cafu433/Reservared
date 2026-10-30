import json
import secrets

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .tiempo import ahora

ESTADOS = {
    "pendiente": "Pendiente",
    "confirmada": "Confirmada",
    "asistio": "Asistió",
    "no_asistio": "No asistió",
    "cancelada": "Cancelada",
}

ESTADOS_PAGO = {
    "sin_pago": "Paga en el lugar",
    "pendiente": "Pago pendiente",
    "pagado": "Pagado",
    "vencido": "Pago no realizado",
}

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

profesional_servicio = db.Table(
    "profesional_servicio",
    db.Column("profesional_id", db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), primary_key=True),
    db.Column("servicio_id", db.Integer, db.ForeignKey("servicio.id", ondelete="CASCADE"), primary_key=True),
)


class Servicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(190), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    duracion = db.Column(db.Integer, nullable=False, default=45)  # minutos
    precio = db.Column(db.Integer, nullable=False, default=0)  # pesos
    modalidad = db.Column(db.String(12), nullable=False, default="presencial")  # presencial | online
    activo = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def online(self):
        return self.modalidad == "online"


class Profesional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(190), nullable=False)
    titulo = db.Column(db.String(190), nullable=False, default="")  # "Psicóloga clínica"
    email = db.Column(db.String(190), nullable=False, default="")
    # Sala fija (Meet, Zoom) para sesiones online cuando no se crea un Meet por cita.
    enlace_sala = db.Column(db.String(500), nullable=False, default="")
    activo = db.Column(db.Boolean, nullable=False, default=True)

    # Sin servicios marcados = atiende todos.
    servicios = db.relationship("Servicio", secondary=profesional_servicio, lazy="selectin")
    horarios = db.relationship("Horario", cascade="all, delete-orphan", order_by="(Horario.dia, Horario.inicio)", lazy="selectin")
    usuario = db.relationship("Usuario", back_populates="profesional", uselist=False)

    def atiende(self, servicio):
        return not self.servicios or any(s.id == servicio.id for s in self.servicios)


class Horario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=False, index=True)
    dia = db.Column(db.Integer, nullable=False)  # 0 = lunes … 6 = domingo
    inicio = db.Column(db.Time, nullable=False)
    fin = db.Column(db.Time, nullable=False)


class Bloqueo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Vacío = bloquea a todos (feriado, cierre).
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=True, index=True)
    inicio = db.Column(db.DateTime, nullable=False, index=True)
    fin = db.Column(db.DateTime, nullable=False)
    motivo = db.Column(db.String(190), nullable=False, default="")

    profesional = db.relationship("Profesional")


class Cita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    servicio_id = db.Column(db.Integer, db.ForeignKey("servicio.id"), nullable=False)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id"), nullable=False)
    inicio = db.Column(db.DateTime, nullable=False, index=True)
    fin = db.Column(db.DateTime, nullable=False)

    nombre = db.Column(db.String(190), nullable=False)
    rut = db.Column(db.String(20), nullable=False, default="")
    email = db.Column(db.String(190), nullable=False)
    telefono = db.Column(db.String(40), nullable=False, default="")
    notas = db.Column(db.Text, nullable=False, default="")  # lo que escribe el paciente
    nota_interna = db.Column(db.Text, nullable=False, default="")  # sólo la ve el equipo

    estado = db.Column(db.String(20), nullable=False, default="confirmada")
    monto = db.Column(db.Integer, nullable=False, default=0)
    estado_pago = db.Column(db.String(20), nullable=False, default="sin_pago")
    pago_ref = db.Column(db.String(64), nullable=False, default="")
    # Mientras espera un pago obligatorio, la hora queda tomada sólo hasta aquí.
    expira = db.Column(db.DateTime, nullable=True)

    enlace_sesion = db.Column(db.String(500), nullable=False, default="")
    google_evento_id = db.Column(db.String(255), nullable=False, default="")

    token = db.Column(db.String(43), nullable=False, unique=True, default=lambda: secrets.token_urlsafe(32))
    origen = db.Column(db.String(10), nullable=False, default="web")  # web | panel
    creada = db.Column(db.DateTime, nullable=False, default=ahora)

    servicio = db.relationship("Servicio", lazy="joined")
    profesional = db.relationship("Profesional", lazy="joined")

    __table_args__ = (db.Index("ix_cita_profesional_inicio", "profesional_id", "inicio"),)

    @property
    def estado_texto(self):
        return ESTADOS.get(self.estado, self.estado)

    @property
    def estado_pago_texto(self):
        return ESTADOS_PAGO.get(self.estado_pago, self.estado_pago)

    @property
    def espera_pago(self):
        return self.estado_pago == "pendiente" and self.expira is not None


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(190), nullable=False, unique=True)
    nombre = db.Column(db.String(190), nullable=False)
    clave_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="profesional")  # admin | profesional
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=True, unique=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    profesional = db.relationship("Profesional", back_populates="usuario")

    @property
    def es_admin(self):
        return self.rol == "admin"

    @property
    def is_active(self):
        return self.activo

    def poner_clave(self, clave):
        self.clave_hash = generate_password_hash(clave)

    def revisar_clave(self, clave):
        return check_password_hash(self.clave_hash, clave)


class Ajuste(db.Model):
    clave = db.Column(db.String(64), primary_key=True)
    valor = db.Column(db.Text, nullable=False, default="null")

    @property
    def dato(self):
        return json.loads(self.valor)
