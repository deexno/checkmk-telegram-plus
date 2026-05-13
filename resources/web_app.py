import configparser
import hashlib
import hmac
import html
import os
import secrets
from datetime import timedelta
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
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def load_config() -> None:
    config.clear()
    config.read(CONFIG_PATH)


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


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.full_path))
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


def configured_web_admin_password() -> str:
    config.read(CONFIG_PATH)
    if not config.has_section("web"):
        return ""
    value = config.get("web", "admin_password", fallback="").strip()
    if value.startswith("<") and value.endswith(">"):
        return ""
    return value


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
        "is_web_admin": bool(session.get("admin_authenticated")),
    }


def validate_csrf() -> None:
    token = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "")
    if not token or not hmac.compare_digest(token, submitted):
        abort(400)


def is_secret_config_key(key: str) -> bool:
    return any(secret in key.lower() for secret in ("token", "password", "secret"))


def config_field_name(section: str, key: str) -> str:
    digest = hashlib.sha256(f"{section}\0{key}".encode("utf-8")).hexdigest()[:16]
    return f"cfg_{digest}"


def config_form_data() -> dict[str, dict[str, dict[str, str | bool]]]:
    form_data = {}
    for section in config.sections():
        form_data[section] = {}
        for key, value in config.items(section):
            is_secret = is_secret_config_key(key)
            form_data[section][key] = {
                "field": config_field_name(section, key),
                "is_secret": is_secret,
                "value": "" if is_secret else value,
                "display_value": "configured" if is_secret and value and not value.startswith("<") else value,
            }
    return form_data


def update_config_from_form() -> list[str]:
    changed = []
    for section in config.sections():
        for key, current_value in list(config.items(section)):
            field_name = config_field_name(section, key)
            if field_name not in request.form:
                continue
            submitted_value = request.form.get(field_name, "")
            if is_secret_config_key(key) and submitted_value == "":
                continue
            if submitted_value != current_value:
                config.set(section, key, submitted_value)
                changed.append(f"{section}.{key}")
    return changed


def save_config() -> None:
    config_path = Path(CONFIG_PATH)
    with config_path.open("w", encoding="utf-8") as configfile:
        config.write(configfile)


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


def host_card(hostname, state, service_problem_count=0):
    css, text = state_badge(state)
    problem_count = int(service_problem_count or 0)
    has_problem = str(state) not in {"0", "OK", "UP"} or problem_count > 0
    if has_problem:
        summary = "Host-Problem" if problem_count == 0 else f"{problem_count} Service-Problem(e)"
    else:
        summary = "Online, keine bekannten Probleme"
    return {
        "hostname": hostname,
        "state": state,
        "badge_css": css,
        "badge_text": text,
        "service_problem_count": problem_count,
        "has_problem": has_problem,
        "summary": summary,
    }


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
            session.permanent = True
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
    return render_template(
        "login.html",
        title="Control Center",
        lead="Melde dich mit dem Bot-Passwort an, um Monitoring und Alerts zu öffnen.",
        field_label="Bot-Passwort",
        button_label="Einloggen",
    )


@app.route("/admin/login", methods=["GET", "POST"])
@require_login
def admin_login():
    if request.method == "POST":
        admin_password = configured_web_admin_password()
        if admin_password and hmac.compare_digest(
            request.form.get("password", ""), admin_password
        ):
            session.permanent = True
            session["admin_authenticated"] = True
            session["csrf_token"] = secrets.token_urlsafe(32)
            storage.add_audit(
                actor_type="web",
                action="web_admin_login",
                details=request.remote_addr or "",
            )
            return redirect(request.args.get("next") or url_for("admin_users"))
        flash(
            "Admin-Login fehlgeschlagen. Admins können das Web-Admin-Passwort im Telegram-Admin-Menü anfordern.",
            "danger",
        )
        storage.add_audit(
            actor_type="web",
            action="web_admin_login_failed",
            details=request.remote_addr or "",
        )
    return render_template(
        "login.html",
        title="Admin Login",
        lead="Für Benutzerverwaltung, Audit und Config ist das separate Web-Admin-Passwort nötig.",
        field_label="Web-Admin-Passwort",
        button_label="Admin entsperren",
    )


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
    host_cards = []
    services = []
    selected_hostgroup = request.values.get("hostgroup", "")
    selected_host = request.values.get("host", "")
    host_status = None
    error = ""

    try:
        hostgroups = checkmk.list_hostgroups()
        if selected_hostgroup:
            hosts = checkmk.list_hosts(selected_hostgroup)
            for hostname in hosts:
                host_cards.append(host_card(hostname, checkmk.host_status(hostname)))
        if selected_host:
            host_status = checkmk.host_status(selected_host)
            services = checkmk.list_services(selected_host)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "monitoring.html",
        hostgroups=hostgroups,
        hosts=hosts,
        host_cards=host_cards,
        services=services,
        selected_hostgroup=selected_hostgroup,
        selected_host=selected_host,
        host_status=host_status,
        state_badge=state_badge,
        error=error,
    )


@app.route("/problems")
@require_login
def problems():
    return redirect(url_for("monitoring", **request.args))


@app.route("/admin/users", methods=["GET", "POST"])
@require_admin
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
    notifications = storage.recent_notifications(100)
    if not event_id and notifications:
        event_id = notifications[0]["event_id"]
    selected_event = storage.notification_event(event_id) if event_id else None
    return render_template(
        "admin_notifications.html",
        notifications=notifications,
        selected_event=selected_event,
        deliveries=storage.notification_deliveries(event_id) if event_id else [],
        actions=storage.audit_for_target(event_id) if event_id else [],
        selected_event_id=event_id,
    )


@app.route("/admin/audit")
@require_admin
def admin_audit():
    return render_template("admin_audit.html", events=storage.recent_audit(150))


@app.route("/admin/config", methods=["GET", "POST"])
@require_admin
def admin_config():
    load_config()
    if request.method == "POST":
        validate_csrf()
        try:
            changed = update_config_from_form()
            save_config()
        except OSError as exc:
            flash(f"Config konnte nicht gespeichert werden: {exc}", "danger")
        else:
            storage.add_audit(
                actor_type="web",
                action="config_updated",
                details=f"ip={request.remote_addr} changed={','.join(changed) or 'none'}",
            )
            if changed:
                flash("Config wurde gespeichert.", "success")
            else:
                flash("Keine Config-Änderungen erkannt.", "info")
            return redirect(url_for("admin_config"))
    return render_template(
        "admin_config.html",
        config_path=CONFIG_PATH,
        safe_config=config_form_data(),
    )


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
