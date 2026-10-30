"""Módulos del panel y quién puede usarlos."""
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

# clave: (nombre, qué permite)
PERMISOS = {
    "dashboard": ("Dashboard", "Ver los números: citas, asistencia, ocupación e ingresos."),
    "agendar": ("Agendar", "Crear, cambiar y cancelar citas; bloquear horas."),
    "agenda": ("Agenda", "Ver la agenda de los profesionales."),
    "pacientes": ("Pacientes", "Ver y editar los datos de los pacientes y su historial de citas."),
    "ficha_clinica": ("Ficha clínica", "Leer y escribir motivo de consulta, antecedentes y notas de evolución."),
    "cobranza": ("Cobranza", "Registrar pagos y ver lo que se debe."),
    "equipo": ("Profesionales y permisos", "Crear perfiles, horarios y cuentas, y dar permisos."),
    "configuracion": ("Configuración", "Servicios, reglas de reserva, pagos en línea y Google."),
    "todo_el_equipo": ("Todo el equipo", "Ver lo de todos los profesionales. Sin esto, una cuenta de profesional ve sólo lo suyo."),
}

PERFILES = {
    "admin": ("Administración", [p for p in PERMISOS if p != "ficha_clinica"]),
    "recepcion": ("Recepción", ["dashboard", "agendar", "agenda", "pacientes", "cobranza", "todo_el_equipo"]),
    "profesional": ("Profesional", ["agendar", "agenda", "pacientes", "ficha_clinica"]),
    "personalizado": ("Personalizado", []),
}


def requiere(permiso):
    def decorador(vista):
        @wraps(vista)
        @login_required
        def envuelta(*a, **kw):
            if not current_user.puede(permiso):
                abort(403)
            return vista(*a, **kw)
        return envuelta
    return decorador
