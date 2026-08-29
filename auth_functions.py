"""
auth_functions.py
Password hashing + login/role helpers for the Thookkupalam feeder app.

Same scheme as the Erattayar (git-feeder-monitor) app: SHA-256 over
(salt + password), rendered as UPPERCASE hex. Kept identical on purpose
so the two apps' `operators` tables stay compatible if you ever want to
share operator accounts between them.
"""

import hashlib
from functools import wraps
from flask import session, redirect, url_for, request


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest().upper()


def is_logged_in() -> bool:
    return bool(session.get("logged_in"))


def login_required(view):
    """Redirects to /login?redirect=<original path> if not logged in."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login", redirect=request.path))
        return view(*args, **kwargs)
    return wrapped


def control_required(view):
    """Like login_required, but also requires the 'controller' role - a
    plain 'viewer' account gets bounced back to the read-only monitor
    with an explanation, instead of reaching the switch controls."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("login", redirect=request.path))
        if session.get("role") != "controller":
            return redirect(url_for(
                "monitor",
                err="Your account is view-only and can't access switch controls.",
            ))
        return view(*args, **kwargs)
    return wrapped
