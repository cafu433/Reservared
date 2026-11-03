import os


def _url_base_de_datos():
    url = os.environ.get("DATABASE_URL", "sqlite:///reservared.db")
    # Render y Neon entregan "postgres://"; SQLAlchemy necesita "postgresql://".
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "://" not in url:
        raise RuntimeError(
            "DATABASE_URL no es una dirección de base de datos. Tiene que empezar con "
            "postgresql:// (cópiala de Neon, la conexión directa, sin -pooler)."
        )
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = _url_base_de_datos()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"

    NOMBRE_NEGOCIO = os.environ.get("NOMBRE_NEGOCIO", "Reservared")
    # Dirección pública de la aplicación, sin "/" al final. Se usa en los
    # enlaces de los correos y en las vueltas de Mercado Pago y Google.
    URL_PUBLICA = os.environ.get("URL_PUBLICA", "").rstrip("/")

    # Primer administrador: se crea al arrancar si todavía no hay usuarios.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    ADMIN_CLAVE = os.environ.get("ADMIN_CLAVE", "")

    # Correo saliente.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PUERTO = int(os.environ.get("SMTP_PUERTO", "587"))
    SMTP_USUARIO = os.environ.get("SMTP_USUARIO", "")
    SMTP_CLAVE = os.environ.get("SMTP_CLAVE", "")
    CORREO_REMITENTE = os.environ.get("CORREO_REMITENTE", "")

    # Mercado Pago (Checkout Pro).
    MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")

    # Webpay Plus (Transbank). Para probar sin código propio: WEBPAY_AMBIENTE=integracion.
    WEBPAY_CODIGO_COMERCIO = os.environ.get("WEBPAY_CODIGO_COMERCIO", "")
    WEBPAY_LLAVE_SECRETA = os.environ.get("WEBPAY_LLAVE_SECRETA", "")
    WEBPAY_AMBIENTE = os.environ.get("WEBPAY_AMBIENTE", "produccion")  # produccion | integracion

    # WhatsApp Business (API de Meta). Las plantillas deben estar aprobadas.
    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
    WHATSAPP_NUMERO_ID = os.environ.get("WHATSAPP_NUMERO_ID", "")
    WHATSAPP_PLANTILLA_CONFIRMACION = os.environ.get("WHATSAPP_PLANTILLA_CONFIRMACION", "confirmacion_hora")
    WHATSAPP_PLANTILLA_RECORDATORIO = os.environ.get("WHATSAPP_PLANTILLA_RECORDATORIO", "recordatorio_hora")
    WHATSAPP_IDIOMA = os.environ.get("WHATSAPP_IDIOMA", "es")

    # Clave para que el servicio de tareas programadas pida los recordatorios.
    CLAVE_TAREAS = os.environ.get("CLAVE_TAREAS", "")

    # Google Calendar y Meet.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")


class ConfigPruebas(Config):
    TESTING = True
    SECRET_KEY = "pruebas"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    URL_PUBLICA = "https://reservared.test"
    MP_ACCESS_TOKEN = "TEST-123"
    GOOGLE_CLIENT_ID = "id-google"
    GOOGLE_CLIENT_SECRET = "secreto-google"
    ADMIN_EMAIL = ""
    WEBPAY_AMBIENTE = "integracion"
    WHATSAPP_TOKEN = "token-wa"
    WHATSAPP_NUMERO_ID = "123"
    CLAVE_TAREAS = "clave-tareas"
