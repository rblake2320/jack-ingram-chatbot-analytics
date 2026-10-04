"""Run from the repository root: python -m src.demo.app."""

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from .api_router import APIRouter
from .claude_client import ClaudeClient, ProviderError
from .config import DEALERSHIP_INFO, defaults
from .routing import LayaRouter
from .store import ConversationChanged, Store


def create_app(overrides=None, router=None):
    app = Flask(__name__)
    app.config.update(defaults())
    app.config.update(overrides or {})
    if not app.config["SECRET_KEY"]:
        if os.getenv("HOST", "127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Public binding requires SESSION_SECRET of at least 32 characters")
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "Temporary local session key; sessions expire on restart. Set SESSION_SECRET to persist."
        )
    if len(app.config["SECRET_KEY"]) < 32:
        raise ValueError("SESSION_SECRET must contain at least 32 characters")
    if app.config["ADMIN_TOKEN"] and len(app.config["ADMIN_TOKEN"]) < 32:
        raise ValueError("ADMIN_TOKEN must contain at least 32 characters")
    if app.config["CHAT_PROVIDER"] not in ("local", "anthropic"):
        raise ValueError("CHAT_PROVIDER must be local or anthropic")
    app.permanent_session_lifetime = timedelta(hours=1)
    store = Store(app.config["DATABASE"])
    app.extensions["store"] = store
    laya = LayaRouter(app.config["LAYA_MODEL_PATH"]) if app.config["ENABLE_LAYA"] else None
    provider = None
    if app.config["CHAT_PROVIDER"] == "anthropic":
        provider = ClaudeClient(app.config["ANTHROPIC_API_KEY"], app.config["ANTHROPIC_MODEL"])
    router = router or APIRouter(provider, laya)
    app.extensions["router"] = router

    def identity():
        session.permanent = True
        if "conversation_id" not in session:
            session["conversation_id"] = secrets.token_urlsafe(32)
        if "visitor" not in session:
            session["visitor"] = secrets.token_urlsafe(32)
        return session["conversation_id"]

    def digest(value):
        return hmac.new(app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()

    @app.before_request
    def guard():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin:
                try:
                    parsed_origin = urlsplit(origin)
                    if parsed_origin.scheme not in ("http", "https") or parsed_origin.netloc != request.host:
                        return jsonify(error="cross_origin_request_denied"), 403
                except ValueError:
                    return jsonify(error="cross_origin_request_denied"), 403
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
                return jsonify(error="cross_origin_request_denied"), 403
            if not request.is_json:
                return jsonify(error="json_required"), 415
            identity()
            if not store.allow("ip:" + digest(request.remote_addr or "unknown"), app.config["RATE_LIMIT"]):
                return jsonify(error="rate_limited", response="Please wait a minute and try again."), 429

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'self'"
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.name.lower().replace(" ", "_")), error.code

    @app.errorhandler(sqlite3.Error)
    def storage_error(error):
        app.logger.error("Storage operation failed: %s", type(error).__name__)
        return jsonify(
            error="storage_unavailable", response="Chat storage is unavailable. Please try later."
        ), 503

    @app.route("/")
    def index():
        identity()
        return render_template(
            "index.html",
            dealership_info=DEALERSHIP_INFO,
            ai_enabled=bool(provider and app.config["ANTHROPIC_API_KEY"]),
        )

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="json_object_required"), 400
        message = data.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            return jsonify(error="message_must_be_1_to_2000_characters"), 400
        if type(data.get("analytics_consent", False)) is not bool:
            return jsonify(error="analytics_consent_must_be_boolean"), 400
        conversation = identity()
        revision, history = store.history(conversation)
        started = time.perf_counter()
        event = {
            "visitor": digest(session["visitor"]),
            "intent": "other",
            "brand": "all",
            "source": "none",
            "outcome": "error",
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        consenting = app.config["ENABLE_ANALYTICS"] and data.get("analytics_consent", False)
        try:
            result = router.process_request(message.strip(), history)
            event.update({key: result[key] for key in ("intent", "brand", "source")})
            event.update(outcome="success", latency_ms=round((time.perf_counter() - started) * 1000, 2))
            usage = result.get("usage", {})
            event.update(
                input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0)
            )
            store.finish(
                conversation,
                revision,
                history
                + [
                    {"role": "user", "content": message.strip()},
                    {"role": "assistant", "content": result["response"]},
                ],
                event if consenting else None,
            )
            return jsonify(**result, conversation_id=conversation)
        except ProviderError as error:
            if consenting:
                event["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                store.event(event, conversation, revision)
            return jsonify(
                error=error.code,
                response="AI service is unavailable. Please try later or call "
                + DEALERSHIP_INFO["phone"]
                + ".",
            ), error.status
        except ConversationChanged:
            return jsonify(
                error="conversation_changed",
                response="Conversation changed while this reply was being prepared. Please resend.",
            ), 409

    @app.route("/api/reset", methods=["POST"])
    @app.route("/api/privacy", methods=["POST"])
    def reset():
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="json_object_required"), 400
        forget = request.path == "/api/privacy"
        store.reset(identity(), digest(session["visitor"]) if forget else None)
        session["conversation_id"] = secrets.token_urlsafe(32)
        if forget:
            session["visitor"] = secrets.token_urlsafe(32)
        return jsonify(status="success", conversation_id=session["conversation_id"])

    @app.route("/api/dealership-info")
    def info():
        return jsonify(DEALERSHIP_INFO)

    @app.route("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return jsonify(
            status="healthy",
            provider=app.config["CHAT_PROVIDER"],
            provider_configured=bool(app.config["ANTHROPIC_API_KEY"]) if provider else True,
            inventory="demo",
            booking="unconfigured",
            crm="unconfigured",
            laya=laya.status if laya else "disabled",
        )

    @app.route("/analytics")
    def dashboard():
        return render_template("analytics.html")

    @app.route("/api/analytics")
    def analytics():
        token = app.config["ADMIN_TOKEN"]
        supplied = request.headers.get("Authorization", "")
        if not token:
            return jsonify(error="analytics_admin_not_configured"), 503
        if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
            return jsonify(error="unauthorized"), 401
        window = request.args.get("window", "all")
        if window not in ("all", "30", "7"):
            return jsonify(error="invalid_window"), 400
        return jsonify(
            window=window, consent_required=True, **store.summary(None if window == "all" else int(window))
        )

    return app


def run_app():
    from waitress import serve

    logging.basicConfig(level=logging.INFO)
    app = create_app()
    serve(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        threads=8,
        max_request_body_size=65_536,
        channel_timeout=30,
    )


if __name__ == "__main__":
    run_app()
