from flask import Blueprint

bp = Blueprint("publico", __name__)

from . import routes  # noqa: E402,F401
