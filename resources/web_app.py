import configparser
import hashlib
import hmac
import html
import os
import secrets
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from checkmk_telegram_plus.checkmk.client import CheckmkBridgeClient
from checkmk_telegram_plus.storage import AppStorage, database_path_from_config


CONFIG_PATH = os.environ.get("CHECKMK_TELEGRAM_PLUS_CONFIG", "config.ini")
config = configparser.RawConfigParser()
config.read(CONFIG_PATH)

omd_site = config.get("check_mk", "site", fallback="default")
bridge_socket_path = (
    config.get(
        "paths",
        "bridge_socket",
        fallback=f"/run/checkmk-telegram-plus/{omd_site}-bridge.sock",
    )
    if config.has_section("paths")
    else f"/run/checkmk-telegram-plus/{omd_site}-bridge.sock"
)
checkmk = CheckmkBridgeClient(bridge_socket_path)
storage = AppStorage(database_path_from_config(config))
storage.migrate_from_config(config)

app = Flask(__name__)
password = config.get("telegram_bot", "password_for_authentication", fallback="")
secret_seed = os.environ.get("CHECKMK_TELEGRAM_PLUS_WEB_SECRET") or f"{password}:{CONFIG_PATH}"
app.secret_key = hashlib.sha256(secret_seed.encode("utf-8")).hexdigest()


def web_setting(key: str, default: str) -> str:
    if not config.has_section("web"):
        return default
    return config.get("web", key, fallback=default)


def require_login(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_globals():
    return {
        "site": omd_site,
        "csrf_token": csrf_token,
        "is_authenticated": bool(session.get("authenticated")),
    }


def validate_csrf() -> None:
    token = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "")
    if not token or not hmac.compare_digest(token, submitted):
        abort(400)


def state_badge(state):
    if str(state) in {"0", "OK", "UP"}:
        return "success", "OK"
    if str(state) in {"1", "WARN"}:
        return "warning", "WARN"
    if str(state) in {"2", "CRIT", "DOWN"}:
        return "danger", "CRIT"
    if str(state) in {"3", "UNKN", "UNKNOWN"}:
        return "secondary", "UNKNOWN"
    return "dark", str(state)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        configured_password = config.get(
            "telegram_bot", "password_for_authentication", fallback=""
        )
        if configured_password and hmac.compare_digest(
            request.form.get("password", ""), configured_password
        ):
            session.clear()
            session["authenticated"] = True
            session["csrf_token"] = secrets.token_urlsafe(32)
            storage.add_audit(
                actor_type="web",
                action="web_login",
                details=request.remote_addr or "",
            )
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Login fehlgeschlagen.", "danger")
        storage.add_audit(
            actor_type="web",
            action="web_login_failed",
            details=request.remote_addr or "",
        )
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@require_login
def logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_login
def dashboard():
    notifications = storage.recent_notifications(8)
    users = storage.list_users()
    queue_path = config.get("paths", "notification_queue", fallback="")
    queue_size = Path(queue_path).stat().st_size if queue_path and Path(queue_path).exists() else 0
    return render_template(
        "dashboard.html",
        notifications=notifications,
        users=users,
        queue_size=queue_size,
    )


@app.route("/monitoring", methods=["GET", "POST"])
@require_login
def monitoring():
    hostgroups = []
    hosts = []
    services = []
    selected_hostgroup = request.values.get("hostgroup", "")
    selected_host = request.values.get("host", "")
    selected_service = request.values.get("service", "")
    host_status = None
    service_details = None
    error = ""

    try:
        hostgroups = checkmk.list_hostgroups()
        if selected_hostgroup:
            hosts = checkmk.list_hosts(selected_hostgroup)
        if selected_host:
            host_status = checkmk.host_status(selected_host)
            services = checkmk.list_services(selected_host)
        if selected_host and selected_service:
            service_details = checkmk.service_details(selected_host, selected_service)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "monitoring.html",
        hostgroups=hostgroups,
        hosts=hosts,
        services=services,
        selected_hostgroup=selected_hostgroup,
        selected_host=selected_host,
        selected_service=selected_service,
        host_status=host_status,
        service_details=service_details,
        state_badge=state_badge,
        error=error,
    )


@app.route("/problems")
@require_login
def problems():
    hostgroups = []
    host_problems = []
    service_problems = []
    selected_hostgroup = request.args.get("hostgroup", "")
    error = ""
    try:
        hostgroups = checkmk.list_hostgroups()
        if selected_hostgroup:
            host_problems = checkmk.host_problems(selected_hostgroup)
            service_problems = checkmk.service_problems(selected_hostgroup)
    except Exception as exc:
        error = str(exc)
    return render_template(
        "problems.html",
        hostgroups=hostgroups,
        selected_hostgroup=selected_hostgroup,
        host_problems=host_problems,
        service_problems=service_problems,
        state_badge=state_badge,
        error=error,
    )


@app.route("/admin/users", methods=["GET", "POST"])
@require_login
def admin_users():
    if request.method == "POST":
        validate_csrf()
        telegram_id = int(request.form["telegram_id"])
        storage.upsert_user(
            telegram_id=telegram_id,
            is_admin=request.form.get("is_admin") == "on",
            notify_loud=request.form.get("notify_loud") == "on",
            notify_silent=request.form.get("notify_silent") == "on",
            active=request.form.get("active") == "on",
        )
        storage.add_audit(
            actor_type="web",
            action="user_updated",
            target=str(telegram_id),
            details=f"ip={request.remote_addr}",
        )
        flash("Benutzer wurde aktualisiert.", "success")
        return redirect(url_for("admin_users"))
    return render_template("admin_users.html", users=storage.list_users())


@app.route("/admin/notifications")
@require_login
def admin_notifications():
    event_id = request.args.get("event_id", "")
    return render_template(
        "admin_notifications.html",
        notifications=storage.recent_notifications(100),
        deliveries=storage.notification_deliveries(event_id) if event_id else [],
        selected_event_id=event_id,
    )


@app.route("/admin/audit")
@require_login
def admin_audit():
    return render_template("admin_audit.html", events=storage.recent_audit(150))


@app.route("/admin/config")
@require_login
def admin_config():
    safe_config = {}
    for section in config.sections():
        safe_config[section] = {}
        for key, value in config.items(section):
            if any(secret in key.lower() for secret in ("token", "password", "secret")):
                safe_config[section][key] = "configured" if value and not value.startswith("<") else ""
            else:
                safe_config[section][key] = value
    return render_template("admin_config.html", config_path=CONFIG_PATH, safe_config=safe_config)


@app.template_filter("state")
def state_filter(value):
    css, text = state_badge(value)
    return f'<span class="badge text-bg-{css}">{html.escape(text)}</span>'


def main() -> None:
    host = web_setting("host", "127.0.0.1")
    port = int(web_setting("port", "8183"))
    try:
        from waitress import serve

        serve(app, host=host, port=port, threads=4)
    except ImportError:
        app.run(host=host, port=port)


if __name__ == "__main__":
    main()
