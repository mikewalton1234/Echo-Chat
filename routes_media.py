# rate_limiter_unavailable
"""HTTP routes for Echo built-in media configuration."""
from __future__ import annotations

from typing import Any, Dict

from flask import jsonify, make_response, render_template
from flask_jwt_extended import get_jwt_identity, jwt_required

from constants import APP_VERSION
from echo_voice_protocol import echo_voice_client_config
from media_mode import client_av_config, media_permissions_policy, media_secure_context_policy
from webrtc_ice_config import ice_server_summary, p2p_ice_servers, redact_ice_servers, voice_ice_servers


def register_media_routes(app, settings: Dict[str, Any], limiter=None) -> None:
    def _no_store(resp):
        try:
            resp.headers["Cache-Control"] = "no-store, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        except Exception:
            pass
        return resp

    def _limit(rule: str):
        try:
            lim = limiter if limiter is not None else app.extensions.get("limiter")
            if lim:
                return lim.limit(rule)
        except Exception:
            pass

        def deco(fn):
            return fn

        return deco


    @app.route("/webrtc-diagnostics", methods=["GET"])
    @app.route("/tools/webrtc-diagnostics", methods=["GET"])
    @jwt_required()
    def webrtc_diagnostics():
        """Browser-run WebRTC/camera/STUN/TURN diagnostic page.

        The checks must run in the user's browser because permissions, device
        availability, HTTPS/localhost status, and ICE candidate selection are
        browser/runtime facts, not server facts.
        """
        user = str(get_jwt_identity() or "")
        p2p_servers = p2p_ice_servers(settings)
        voice_servers = voice_ice_servers(settings)
        media_cfg = {**echo_voice_client_config(settings), **client_av_config(settings)}
        safe_cfg = {
            **media_cfg,
            "p2p_ice_servers": redact_ice_servers(p2p_servers),
            "voice_ice_servers": redact_ice_servers(voice_servers),
            "ice_summary": ice_server_summary(settings),
        }
        # Keep credentials out of the copied/report JSON while still giving the
        # browser the real authenticated ICE config needed to test TURN relay.
        diag_config = {
            "username": user,
            "app_version": APP_VERSION,
            "safe_config": safe_cfg,
            "runtime_ice": {
                "p2p_ice_servers": p2p_servers,
                "voice_ice_servers": voice_servers,
            },
        }
        resp = make_response(render_template(
            "webrtc_diagnostics.html",
            username=user,
            app_version=APP_VERSION,
            diag_config=diag_config,
        ))
        return _no_store(resp)

    @app.route("/api/webrtc/ice", methods=["GET"])
    @_limit(settings.get("rate_limit_webrtc_ice") or "120 per minute")
    @jwt_required()
    def webrtc_ice_config():
        """Return authenticated runtime ICE config for browser WebRTC clients/tools."""
        return _no_store(jsonify(
            {
                "ok": True,
                "p2p_ice_servers": p2p_ice_servers(settings),
                "voice_ice_servers": voice_ice_servers(settings),
                "summary": ice_server_summary(settings),
                "secure_context": media_secure_context_policy(settings),
            }
        ))

    @app.route("/api/av/mode", methods=["GET"])
    @_limit(settings.get("rate_limit_media_mode") or "120 per minute")
    @jwt_required()
    def av_mode():
        decision = client_av_config(settings)
        secure_context = media_secure_context_policy(settings)
        client_config = {**echo_voice_client_config(settings), **decision, "secure_context": secure_context}
        return _no_store(jsonify({"ok": True, **decision, "secure_context": secure_context, "permissions_policy": media_permissions_policy(settings), "client_config": client_config}))
