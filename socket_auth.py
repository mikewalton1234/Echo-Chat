"""Socket.IO auth helpers.

Browser long-polling transports send the JWT cookies, but custom CSRF headers
are not always available on every Engine.IO request. WebSocket transports also
keep the cookies from the original handshake, so re-validating a short-lived
access cookie on every Socket.IO event can disconnect an otherwise valid live
realtime session after the browser has already refreshed its HTTP access token.

For same-origin EchoChat Socket.IO events we therefore:

  1) verify the normal Flask-JWT-Extended access cookie during connect;
  2) bind the Socket.IO sid to the authenticated EchoChat auth session;
  3) trust that established sid for later Socket.IO events while still checking
     the auth session row for revocation/idle timeout in the event handlers.

Regular HTTP routes continue to enforce JWT+CSRF normally.
"""

from __future__ import annotations

from functools import wraps
import logging

from flask import request, session
from flask_jwt_extended import get_jwt_identity as _jwt_get_identity
from flask_jwt_extended import get_jwt as _jwt_get_jwt
from flask_jwt_extended import verify_jwt_in_request
from flask_jwt_extended.exceptions import CSRFError, NoAuthorizationError

from database import close_db


def _set_socket_identity(value, source: str) -> None:
    try:
        request._echochat_socket_identity = value
        request._echochat_socket_identity_source = source
    except Exception:
        pass


def _set_socket_claims(claims: dict | None, source: str) -> None:
    try:
        request._echochat_socket_claims = dict(claims or {})
        request._echochat_socket_claims_source = source
    except Exception:
        pass


def _get_established_socket_session() -> dict | None:
    """Return the connected-session record already bound to this Socket.IO sid."""
    try:
        sid = getattr(request, "sid", None)
    except Exception:
        sid = None
    if not sid:
        return None

    try:
        from realtime.state import get_connected_session  # local import avoids cycles
        sess = get_connected_session(str(sid)) or {}
        username = str(sess.get("username") or "").strip()
        if username:
            return sess
    except Exception:
        pass

    # Compatibility fallback for older tests/import paths.
    try:
        from realtime.state import CONNECTED_USERS, CONNECTED_USERS_LOCK  # local import avoids cycles
        with CONNECTED_USERS_LOCK:
            sess = dict(CONNECTED_USERS.get(str(sid)) or {})
        username = str(sess.get("username") or "").strip()
        if username:
            return sess
    except Exception:
        pass
    return None


def _get_established_socket_identity():
    sess = _get_established_socket_session() or {}
    username = str(sess.get("username") or "").strip()
    return username or None


def _claims_from_established_socket_session() -> dict | None:
    sess = _get_established_socket_session() or {}
    username = str(sess.get("username") or "").strip()
    if not username:
        return None
    sid = str(sess.get("auth_session_id") or "").strip()
    claims = {"sub": username, "type": "access", "fresh": False, "echo_socket_session": True}
    if sid:
        claims["sid"] = sid
    return claims


def get_jwt_identity():
    """Return the current Socket.IO identity.

    Prefers the identity cached by our wrapper, falls back to Flask-JWT, then to
    the established Socket.IO sid, and finally the signed Flask session username
    for same-origin socket traffic.
    """
    try:
        cached = getattr(request, "_echochat_socket_identity", None)
        if cached:
            return cached
    except Exception:
        pass

    try:
        ident = _jwt_get_identity()
        if ident:
            _set_socket_identity(ident, "jwt")
            return ident
    except Exception:
        pass

    try:
        ident = _get_established_socket_identity()
        if ident:
            _set_socket_identity(ident, "socket_session")
            return ident
    except Exception:
        pass

    try:
        ident = session.get("username")
        if ident:
            _set_socket_identity(str(ident), "session")
            return str(ident)
    except Exception:
        pass
    return None


def get_jwt() -> dict:
    """Return JWT-like claims for Socket.IO handlers.

    After connect, browser WebSocket packets may not carry the rotated HTTP
    access cookie. Event handlers only need the EchoChat auth session id (sid)
    and identity, so synthesize those from the established Socket.IO session.
    """
    try:
        cached = getattr(request, "_echochat_socket_claims", None)
        if isinstance(cached, dict) and cached:
            return dict(cached)
    except Exception:
        pass

    try:
        claims = _jwt_get_jwt() or {}
        if claims:
            _set_socket_claims(claims, "jwt")
            return dict(claims)
    except Exception:
        pass

    claims = _claims_from_established_socket_session()
    if claims:
        _set_socket_claims(claims, "socket_session")
        return dict(claims)
    return {}


def get_socket_identity_source() -> str | None:
    try:
        src = getattr(request, "_echochat_socket_identity_source", None)
        if src:
            return str(src)
    except Exception:
        pass
    try:
        if _get_established_socket_identity():
            return "socket_session"
    except Exception:
        pass
    try:
        if session.get("username"):
            return "session"
    except Exception:
        pass
    return None


def jwt_required(optional: bool = False, **kwargs):
    """Socket-safe auth decorator with established-session fallback.

    This is intentionally for Socket.IO handlers only. HTTP routes should keep
    using flask_jwt_extended.jwt_required directly.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kw):
            established_ident = None
            try:
                established_ident = _get_established_socket_identity()
            except Exception:
                established_ident = None

            # After the connect handler authenticates a sid, later Socket.IO
            # events should trust that established socket identity. Re-running
            # HTTP-style cookie+CSRF JWT verification on every packet is brittle
            # in long-polling mode and impossible to keep fresh for an already
            # upgraded WebSocket handshake.
            if established_ident:
                _set_socket_identity(str(established_ident), "socket_session")
                claims = _claims_from_established_socket_session()
                if claims:
                    _set_socket_claims(claims, "socket_session")
                return fn(*args, **kw)

            try:
                verify_jwt_in_request(optional=optional, **kwargs)
                ident = None
                claims = {}
                try:
                    ident = _jwt_get_identity()
                except Exception:
                    ident = None
                try:
                    claims = _jwt_get_jwt() or {}
                except Exception:
                    claims = {}
                try:
                    close_db()
                except Exception:
                    pass
                if ident:
                    _set_socket_identity(ident, "jwt")
                else:
                    try:
                        sess_ident = session.get("username")
                    except Exception:
                        sess_ident = None
                    if sess_ident:
                        _set_socket_identity(str(sess_ident), "session")
                if claims:
                    _set_socket_claims(claims, "jwt")
                return fn(*args, **kw)
            except (CSRFError, NoAuthorizationError) as exc:
                try:
                    close_db()
                except Exception:
                    pass
                try:
                    sess_ident = session.get("username")
                except Exception:
                    sess_ident = None
                if sess_ident:
                    logging.debug("[socket-auth] falling back to Flask session after %s", exc.__class__.__name__)
                    _set_socket_identity(str(sess_ident), "session")
                    return fn(*args, **kw)
                if optional:
                    _set_socket_identity(None, "optional")
                    return fn(*args, **kw)
                raise
        return wrapper
    return decorator
