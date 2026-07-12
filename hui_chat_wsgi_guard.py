#!/usr/bin/env python3
"""Dependency-light WSGI start_response guard for Hui Chat.

This module intentionally has no Flask imports so the small WSGI unit tests can
exercise the guard even before the full runtime dependency stack is installed.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable


class HuiChatStartResponseGuard:
    """Last-resort guard for noisy dev-server WSGI edge cases.

    Werkzeug's built-in development server asserts if a WSGI branch returns an
    empty iterable without ever calling ``start_response``. Flask normally does
    the right thing, but Socket.IO long-polling / upgrade disconnect edges can
    occasionally expose an invalid empty WSGI response path.

    This wrapper does not hide normal application exceptions. It only handles
    invalid WSGI responses by returning an explicit 204 for empty responses or
    an explicit 500 when bytes are yielded before ``start_response``.
    """

    def __init__(self, app: Callable):
        self.app = app

    def __call__(self, environ, start_response):
        start_response_called = False

        def _tracking_start_response(status, headers, exc_info=None):
            nonlocal start_response_called
            start_response_called = True
            return start_response(status, headers, exc_info)

        app_iter = self.app(environ, _tracking_start_response)

        def _guarded_iter():
            nonlocal start_response_called
            try:
                for chunk in app_iter:
                    if not start_response_called:
                        method = environ.get("REQUEST_METHOD", "?")
                        path = environ.get("PATH_INFO", "?")
                        logging.error(
                            "WSGI app yielded response data before start_response; "
                            "returning 500 method=%s path=%s",
                            method,
                            path,
                        )
                        body = b"Internal Server Error"
                        start_response(
                            "500 Internal Server Error",
                            [
                                ("Content-Type", "text/plain; charset=utf-8"),
                                ("Content-Length", str(len(body))),
                                ("Connection", "close"),
                            ],
                        )
                        start_response_called = True
                        yield body
                        return
                    yield chunk

                if not start_response_called:
                    method = environ.get("REQUEST_METHOD", "?")
                    path = environ.get("PATH_INFO", "?")
                    upgrade = environ.get("HTTP_UPGRADE", "")
                    transport = environ.get("QUERY_STRING", "")
                    logging.warning(
                        "WSGI app returned without start_response; returning 204 "
                        "method=%s path=%s upgrade=%s query=%s",
                        method,
                        path,
                        upgrade,
                        transport,
                    )
                    start_response(
                        "204 No Content",
                        [
                            ("Content-Length", "0"),
                            ("Cache-Control", "no-store"),
                            ("Connection", "close"),
                        ],
                    )
            finally:
                close = getattr(app_iter, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception:
                        logging.exception("Failed to close guarded WSGI iterator")

        return _guarded_iter()
