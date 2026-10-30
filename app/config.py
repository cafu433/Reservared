import os


def _url_base_de_datos():
    url = os.environ.get("DATABASE_URL", "sqlite:///reservared.db")
    # Render y Neon entregan "postgres://"; SQLAlchemy necesita "postgresql://".
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
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
