from functools import wraps

from flask import abort, redirect, url_for
from flask_login import current_user


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login_page"))

        if not current_user.role or current_user.role.name.upper() != "ADMIN":
            abort(403)

        return view_func(*args, **kwargs)

    return wrapped_view