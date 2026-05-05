from functools import wraps

from flask import abort
from flask_login import current_user


def permission_required(permission_code):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            if not current_user.has_permission(permission_code):
                abort(403)

            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator