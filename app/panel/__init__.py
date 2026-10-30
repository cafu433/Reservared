from flask import Blueprint

bp = Blueprint("panel", __name__)


@bp.after_request
def no_incrustar(resp):
    # El panel nunca se muestra dentro de otra página.
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Cache-Control"] = "no-store"
    return resp


from . import routes  # noqa: E402,F401
