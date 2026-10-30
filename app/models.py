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
    "por_cobrar": "Por cobrar",
    "pendiente": "Pago en línea pendiente",
    "parcial": "Abonado",
    "pagado": "Pagado",
    "sin_costo": "Sin costo",
    "vencido": "Pago no realizado",
}

MEDIOS_PAGO = {
    "efectivo": "Efectivo",
    "transferencia": "Transferencia",
    "debito": "Débito",
    "credito": "Crédito",
    "webpay": "Webpay",
    "mercadopago": "Mercado Pago",
    "otro": "Otro",
}

PREVISIONES = ["Fonasa", "Isapre", "Particular", "Otra"]

MOTIVOS_CANCELACION = [
    "Problema de horario", "Enfermedad", "Se siente mejor", "Costo", "Se atenderá en otro lugar",
    "Profesional no disponible", "Otro",
]

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

profesional_servicio = db.Table(
    "profesional_servicio",
    db.Column("profesional_id", db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), primary_key=True),
    db.Column("servicio_id", db.Integer, db.ForeignKey("servicio.id", ondelete="CASCADE"), primary_key=True),
)


profesional_especialidad = db.Table(
    "profesional_especialidad",
    db.Column("profesional_id", db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), primary_key=True),
    db.Column("especialidad_id", db.Integer, db.ForeignKey("especialidad.id", ondelete="CASCADE"), primary_key=True),
)

MODALIDADES_TRAMO = {"ambas": "Presencial y online", "presencial": "Sólo presencial", "online": "Sólo online"}


class Especialidad(db.Model):
    """Áreas que atiende un profesional: psicología prenatal, infantil…"""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False, unique=True)


class Sucursal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    direccion = db.Column(db.String(255), nullable=False, default="")
    telefono = db.Column(db.String(40), nullable=False, default="")
    indicaciones = db.Column(db.Text, nullable=False, default="")  # "Piso 3, oficina 302"
    activa = db.Column(db.Boolean, nullable=False, default=True)


class Servicio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(190), nullable=False)
    categoria = db.Column(db.String(120), nullable=False, default="")  # tipo: Psicología, Nutrición…
    descripcion = db.Column(db.Text, nullable=False, default="")
    duracion = db.Column(db.Integer, nullable=False, default=45)  # minutos
    precio = db.Column(db.Integer, nullable=False, default=0)  # pesos
    modalidad = db.Column(db.String(12), nullable=False, default="presencial")  # presencial | online | ambas
    activo = db.Column(db.Boolean, nullable=False, default=True)

    tarifas = db.relationship("Tarifa", back_populates="servicio", cascade="all, delete-orphan", lazy="selectin")

    @property
    def online(self):
        return self.modalidad == "online"

    @property
    def modalidades(self):
        return ["presencial", "online"] if self.modalidad == "ambas" else [self.modalidad]


class Tarifa(db.Model):
    """Precio especial de un servicio. Los campos vacíos valen para todos; gana
    la regla que calza en más campos."""
    id = db.Column(db.Integer, primary_key=True)
    servicio_id = db.Column(db.Integer, db.ForeignKey("servicio.id", ondelete="CASCADE"), nullable=False, index=True)
    modalidad = db.Column(db.String(12), nullable=False, default="")  # "" | presencial | online
    especialidad_id = db.Column(db.Integer, db.ForeignKey("especialidad.id", ondelete="CASCADE"), nullable=True)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=True)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursal.id", ondelete="CASCADE"), nullable=True)
    precio = db.Column(db.Integer, nullable=False)

    servicio = db.relationship("Servicio", back_populates="tarifas")
    especialidad = db.relationship("Especialidad")
    profesional = db.relationship("Profesional")
    sucursal = db.relationship("Sucursal")


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
    especialidades = db.relationship("Especialidad", secondary=profesional_especialidad, lazy="selectin",
                                     order_by="Especialidad.nombre")
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
    modalidad = db.Column(db.String(12), nullable=False, default="ambas")  # ambas | presencial | online
    # Dónde atiende en ese tramo si es presencial. Vacío = sin sucursal (un solo local).
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursal.id", ondelete="SET NULL"), nullable=True)

    sucursal = db.relationship("Sucursal")

    def sirve_para(self, modalidad):
        return self.modalidad == "ambas" or not modalidad or self.modalidad == modalidad


class Bloqueo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Vacío = bloquea a todos (feriado, cierre).
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=True, index=True)
    inicio = db.Column(db.DateTime, nullable=False, index=True)
    fin = db.Column(db.DateTime, nullable=False)
    motivo = db.Column(db.String(190), nullable=False, default="")

    profesional = db.relationship("Profesional")


class Paciente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(190), nullable=False)
    rut = db.Column(db.String(20), nullable=False, default="", index=True)
    email = db.Column(db.String(190), nullable=False, default="", index=True)
    telefono = db.Column(db.String(40), nullable=False, default="")
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    prevision = db.Column(db.String(40), nullable=False, default="")
    direccion = db.Column(db.String(255), nullable=False, default="")
    contacto_emergencia = db.Column(db.String(255), nullable=False, default="")
    notas = db.Column(db.Text, nullable=False, default="")  # administrativas: las ve el equipo
    # Ficha clínica: sólo con el permiso "ficha_clinica".
    motivo_consulta = db.Column(db.Text, nullable=False, default="")
    antecedentes = db.Column(db.Text, nullable=False, default="")
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    evoluciones = db.relationship("Evolucion", back_populates="paciente", order_by="Evolucion.fecha.desc()",
                                  lazy="dynamic", cascade="all, delete-orphan")
    citas = db.relationship("Cita", back_populates="paciente", order_by="Cita.inicio.desc()", lazy="dynamic")

    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None
        hoy = ahora().date()
        n = self.fecha_nacimiento
        return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))


class Evolucion(db.Model):
    """Nota clínica de una sesión."""
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("paciente.id", ondelete="CASCADE"), nullable=False, index=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("cita.id", ondelete="SET NULL"), nullable=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="SET NULL"), nullable=True)
    fecha = db.Column(db.DateTime, nullable=False, default=ahora)
    texto = db.Column(db.Text, nullable=False)
    editada = db.Column(db.DateTime, nullable=True)

    paciente = db.relationship("Paciente", back_populates="evoluciones")
    cita = db.relationship("Cita")
    autor = db.relationship("Usuario")
    profesional = db.relationship("Profesional")


class Cita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("paciente.id"), nullable=True, index=True)
    servicio_id = db.Column(db.Integer, db.ForeignKey("servicio.id"), nullable=False)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursal.id", ondelete="SET NULL"), nullable=True, index=True)
    especialidad_id = db.Column(db.Integer, db.ForeignKey("especialidad.id", ondelete="SET NULL"), nullable=True)
    modalidad = db.Column(db.String(12), nullable=False, default="presencial")  # presencial | online
    inicio = db.Column(db.DateTime, nullable=False, index=True)
    fin = db.Column(db.DateTime, nullable=False)

    nombre = db.Column(db.String(190), nullable=False)
    rut = db.Column(db.String(20), nullable=False, default="")
    email = db.Column(db.String(190), nullable=False)
    telefono = db.Column(db.String(40), nullable=False, default="")
    notas = db.Column(db.Text, nullable=False, default="")  # lo que escribe el paciente
    nota_interna = db.Column(db.Text, nullable=False, default="")  # sólo la ve el equipo

    estado = db.Column(db.String(20), nullable=False, default="confirmada")
    precio = db.Column(db.Integer, nullable=False, default=0)  # lo que vale esta cita
    monto = db.Column(db.Integer, nullable=False, default=0)  # lo que se cobra en línea al reservar
    estado_pago = db.Column(db.String(20), nullable=False, default="por_cobrar")
    pago_ref = db.Column(db.String(64), nullable=False, default="")
    # Mientras espera un pago obligatorio, la hora queda tomada sólo hasta aquí.
    expira = db.Column(db.DateTime, nullable=True)

    recordatorio_enviado = db.Column(db.DateTime, nullable=True)
    cancelada_en = db.Column(db.DateTime, nullable=True)
    cancelada_por = db.Column(db.String(20), nullable=False, default="")  # paciente | equipo | sistema
    motivo_cancelacion = db.Column(db.String(255), nullable=False, default="")
    reagendada = db.Column(db.Integer, nullable=False, default=0)  # veces que se movió
    enlace_sesion = db.Column(db.String(500), nullable=False, default="")
    google_evento_id = db.Column(db.String(255), nullable=False, default="")

    token = db.Column(db.String(43), nullable=False, unique=True, default=lambda: secrets.token_urlsafe(32))
    origen = db.Column(db.String(10), nullable=False, default="web")  # web | panel
    creada = db.Column(db.DateTime, nullable=False, default=ahora)

    servicio = db.relationship("Servicio", lazy="joined")
    profesional = db.relationship("Profesional", lazy="joined")
    paciente = db.relationship("Paciente", back_populates="citas")
    sucursal = db.relationship("Sucursal", lazy="joined")
    especialidad = db.relationship("Especialidad")

    @property
    def online(self):
        return self.modalidad == "online"
    pagos = db.relationship("Pago", back_populates="cita", order_by="Pago.fecha", lazy="selectin")

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

    def cancelar(self, por, motivo=""):
        self.estado = "cancelada"
        self.cancelada_en = ahora()
        self.cancelada_por = por
        self.motivo_cancelacion = (motivo or "")[:255]

    @property
    def pagado(self):
        return sum(p.monto for p in self.pagos)

    @property
    def saldo(self):
        return max(0, self.precio - self.pagado)


class PagoEnLinea(db.Model):
    """Un intento de pago en Webpay o Mercado Pago, mientras se resuelve."""
    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("cita.id", ondelete="CASCADE"), nullable=False, index=True)
    pasarela = db.Column(db.String(20), nullable=False)  # webpay | mercadopago
    orden = db.Column(db.String(40), nullable=False, unique=True)
    token = db.Column(db.String(128), nullable=False, default="", index=True)
    monto = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="iniciado")  # iniciado | aprobado | rechazado
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    cita = db.relationship("Cita")


class Pago(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey("cita.id", ondelete="SET NULL"), nullable=True, index=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("paciente.id"), nullable=True, index=True)
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id"), nullable=True, index=True)
    monto = db.Column(db.Integer, nullable=False)
    medio = db.Column(db.String(20), nullable=False, default="efectivo")
    fecha = db.Column(db.Date, nullable=False, index=True)
    referencia = db.Column(db.String(120), nullable=False, default="")  # n.º de operación, boleta…
    nota = db.Column(db.String(255), nullable=False, default="")
    registrado_por = db.Column(db.Integer, db.ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True)
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    cita = db.relationship("Cita", back_populates="pagos")
    paciente = db.relationship("Paciente")
    profesional = db.relationship("Profesional")
    usuario = db.relationship("Usuario")

    @property
    def medio_texto(self):
        return MEDIOS_PAGO.get(self.medio, self.medio)


class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(190), nullable=False, unique=True)
    nombre = db.Column(db.String(190), nullable=False)
    clave_hash = db.Column(db.String(255), nullable=False)
    # Perfil de partida (admin, recepcion, profesional, personalizado). La
    # administración puede todo; el resto, lo que diga "permisos".
    rol = db.Column(db.String(20), nullable=False, default="profesional")
    permisos = db.Column(db.Text, nullable=False, default="[]")
    profesional_id = db.Column(db.Integer, db.ForeignKey("profesional.id", ondelete="CASCADE"), nullable=True, unique=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime, nullable=False, default=ahora)

    profesional = db.relationship("Profesional", back_populates="usuario")

    @property
    def es_admin(self):
        return self.rol == "admin"

    @property
    def lista_permisos(self):
        try:
            return set(json.loads(self.permisos or "[]"))
        except ValueError:
            return set()

    def poner_permisos(self, lista):
        self.permisos = json.dumps(sorted(set(lista)))

    def puede(self, permiso):
        # La ficha clínica es confidencial: ni la administración la ve sin el permiso explícito.
        if permiso == "ficha_clinica":
            return permiso in self.lista_permisos
        return self.es_admin or permiso in self.lista_permisos

    @property
    def ve_todo(self):
        """Ve la agenda, los pacientes y la cobranza de todo el equipo."""
        return self.puede("todo_el_equipo") or not self.profesional_id

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
