import logging

import click
from flask import Flask
from sqlalchemy import inspect

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .tiempo import dia_largo, fecha_larga, pesos


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .models import Usuario

    @login_manager.user_loader
    def cargar_usuario(uid):
        return db.session.get(Usuario, int(uid))

    from .panel import bp as panel_bp
    from .publico import bp as publico_bp

    app.register_blueprint(publico_bp)
    app.register_blueprint(panel_bp, url_prefix="/panel")

    app.jinja_env.filters["pesos"] = pesos
    app.jinja_env.filters["fecha_larga"] = fecha_larga
    app.jinja_env.filters["dia_largo"] = dia_largo

    @app.context_processor
    def globales():
        return {"negocio": app.config["NOMBRE_NEGOCIO"]}

    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.get("/healthz")
    def salud():
        return "ok"

    @app.cli.command("crear-admin")
    @click.argument("email")
    @click.argument("clave")
    @click.option("--nombre", default="Administración")
    def crear_admin(email, clave, nombre):
        """Crea (o reactiva) una cuenta de administración."""
        u = Usuario.query.filter_by(email=email.lower()).first() or Usuario(email=email.lower(), nombre=nombre)
        u.rol, u.activo = "admin", True
        u.poner_clave(clave)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Listo: {u.email} puede entrar a /panel")

    if not app.testing:
        with app.app_context():
            _primer_admin(app)

    return app


def _primer_admin(app):
    """En Render no hay consola en el plan gratis: el primer administrador sale
    de ADMIN_EMAIL y ADMIN_CLAVE la primera vez que arranca la aplicación."""
    from .models import Usuario

    email, clave = app.config["ADMIN_EMAIL"].strip().lower(), app.config["ADMIN_CLAVE"]
    try:
        if not email or not clave or not inspect(db.engine).has_table("usuario"):
            return
        if Usuario.query.first() is None:
            u = Usuario(email=email, nombre="Administración", rol="admin")
            u.poner_clave(clave)
            db.session.add(u)
            db.session.commit()
            app.logger.info("Se creó la cuenta de administración %s", email)
    except Exception:
        db.session.rollback()
        app.logger.exception("No se pudo crear el primer administrador")
