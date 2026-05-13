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
    g,
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

SUPPORTED_LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"
TRANSLATIONS = {
    "de": {
        "active": "aktiv",
        "active_users": "Aktive Benutzer",
        "actor": "Actor",
        "action": "Aktion",
        "actions_for_alert": "Aktionen zum Alert",
        "admin_login": "Admin Login",
        "admin_login_button": "Admin entsperren",
        "admin_login_failed": "Admin-Login fehlgeschlagen. Admins können das Web-Admin-Passwort im Telegram-Admin-Menü anfordern.",
        "admin_login_lead": "Für Benutzerverwaltung, Audit und Config ist das separate Web-Admin-Passwort nötig.",
        "admin_password": "Web-Admin-Passwort",
        "all_show": "Alle anzeigen",
        "alert_message": "Alert-Nachricht",
        "audit_empty": "Noch keine Audit-Einträge.",
        "audit_events": "Audit Events",
        "audit_lead": "Anmeldungen, Useränderungen und kritische Aktionen an einem Ort.",
        "audit_log": "Audit-Log",
        "by": "von",
        "cancel": "Verwerfen",
        "config_empty_changes": "Keine Config-Änderungen erkannt.",
        "config_lead": "Aktive Config bearbeiten. Leere Secret-Felder behalten den bisherigen Wert.",
        "config_saved": "Config wurde gespeichert.",
        "config_save": "Config speichern",
        "config_save_failed": "Config konnte nicht gespeichert werden: {error}",
        "configuration": "Konfiguration",
        "current_value": "Aktuell",
        "dashboard_lead": "Schneller Überblick über Benutzer, Queue und die letzten versendeten Alerts.",
        "delivery_click_details": "Delivery-Zähler anklicken, um Details zu sehen.",
        "delivery_click_message": "Delivery-Zähler anklicken, um Nachricht, Ausgabe und Details zu sehen.",
        "deliveries": "Zustellungen",
        "details": "Details",
        "entries_count": "{count} Einträge",
        "events_count": "{count} Events",
        "host": "Host",
        "host_check": "Host prüfen",
        "host_choose": "Host auswählen",
        "host_choose_after_group": "Nach Gruppe wählen",
        "host_problem": "Host-Problem",
        "host_search": "Host suchen",
        "host_service_lookup": "Host & Service Lookup",
        "host_status": "HOST STATUS",
        "hosts": "Hosts",
        "hostgroup": "Hostgruppe",
        "hostgroup_choose": "Hostgruppe auswählen",
        "hostgroup_search": "Hostgruppe suchen",
        "hosts_show": "Hosts anzeigen",
        "ip_address": "IP-Adresse",
        "language": "Sprache",
        "last_alerts": "Letzte Alerts",
        "login": "Einloggen",
        "login_failed": "Login fehlgeschlagen.",
        "login_lead": "Melde dich mit dem Bot-Passwort an, um Monitoring und Alerts zu öffnen.",
        "logout": "Logout",
        "monitoring_cockpit": "Monitoring Cockpit",
        "monitoring_lead": "Wähle Hostgruppe und Host. Die Ansicht zeigt danach alle Services automatisch.",
        "nav_close": "Navigation schließen",
        "nav_open": "Navigation öffnen",
        "no_alert_actions": "Noch keine Rechecks, Graph-, Help- oder Acknowledge-Aktionen für dieses Event.",
        "no_alerts": "Noch keine Alerts.",
        "no_alerts_logged": "Noch keine Alerts geloggt.",
        "no_deliveries": "Keine Zustellungen für dieses Event.",
        "no_hostgroups": "Keine Hostgruppen gefunden.",
        "no_hosts": "Keine Hosts in dieser Hostgruppe gefunden.",
        "no_services": "Keine Services gefunden.",
        "no_users": "Noch keine Benutzer in der Datenbank.",
        "not_selected": "Noch nicht gewählt",
        "notification_delivery_lead": "Nachvollziehen, welche Notifications erzeugt und an wen sie zugestellt wurden.",
        "notification_subscriptions": "Notification-Abos",
        "output": "Ausgabe",
        "password": "Bot-Passwort",
        "queue_file_size": "Queue-Dateigröße",
        "quick_actions": "Schnellaktionen",
        "raw_event": "Raw Event",
        "roles_subscriptions": "Rollen und Abos",
        "runtime_config": "Runtime Config",
        "save": "Speichern",
        "select_alert": "Alert auswählen, um Aktionen zu sehen.",
        "selected_event_missing": "Das ausgewählte Event wurde nicht gefunden.",
        "sent": "Gesendet",
        "service": "Service",
        "service_available": "Service erreichbar",
        "service_problem_count": "{count} Service-Problem(e)",
        "smart_instructions": "Smart Notification Instructions",
        "source": "Quelle",
        "status": "Status",
        "system": "System",
        "telegram_users": "Telegram Benutzer",
        "to": "an",
        "type": "Typ",
        "user": "User",
        "user_updated": "Benutzer wurde aktualisiert.",
        "users": "Benutzer",
        "users_lead": "Rollen und Notification-Abos werden in SQLite verwaltet, nicht mehr in der Config.",
        "users_management": "Benutzerverwaltung",
        "target": "Ziel",
        "time": "Zeit",
        "online_no_problems": "Online, keine bekannten Probleme",
        "with_problem": "mit Problem",
    },
    "en": {
        "active": "active",
        "active_users": "Active users",
        "actor": "Actor",
        "action": "Action",
        "actions_for_alert": "Alert actions",
        "admin_login": "Admin Login",
        "admin_login_button": "Unlock admin",
        "admin_login_failed": "Admin login failed. Admins can request the web admin password in the Telegram admin menu.",
        "admin_login_lead": "User management, audit and config require the separate web admin password.",
        "admin_password": "Web admin password",
        "all_show": "Show all",
        "alert_message": "Alert message",
        "audit_empty": "No audit entries yet.",
        "audit_events": "Audit events",
        "audit_lead": "Logins, user changes and critical actions in one place.",
        "audit_log": "Audit log",
        "by": "by",
        "cancel": "Discard",
        "config_empty_changes": "No config changes detected.",
        "config_lead": "Edit the active config. Empty secret fields keep their current value.",
        "config_saved": "Config was saved.",
        "config_save": "Save config",
        "config_save_failed": "Config could not be saved: {error}",
        "configuration": "Configuration",
        "current_value": "Current",
        "dashboard_lead": "Quick overview of users, queue and recently sent alerts.",
        "delivery_click_details": "Click a delivery counter to see details.",
        "delivery_click_message": "Click a delivery counter to see the message, output and details.",
        "deliveries": "Deliveries",
        "details": "Details",
        "entries_count": "{count} entries",
        "events_count": "{count} events",
        "host": "Host",
        "host_check": "Check host",
        "host_choose": "Select host",
        "host_choose_after_group": "Select group first",
        "host_problem": "Host problem",
        "host_search": "Search host",
        "host_service_lookup": "Host & Service Lookup",
        "host_status": "HOST STATUS",
        "hosts": "Hosts",
        "hostgroup": "Host group",
        "hostgroup_choose": "Select host group",
        "hostgroup_search": "Search host group",
        "hosts_show": "Show hosts",
        "ip_address": "IP address",
        "language": "Language",
        "last_alerts": "Recent alerts",
        "login": "Sign in",
        "login_failed": "Login failed.",
        "login_lead": "Sign in with the bot password to open monitoring and alerts.",
        "logout": "Logout",
        "monitoring_cockpit": "Monitoring Cockpit",
        "monitoring_lead": "Choose a host group and host. Services are shown automatically afterwards.",
        "nav_close": "Close navigation",
        "nav_open": "Open navigation",
        "no_alert_actions": "No recheck, graph, help or acknowledge actions for this event yet.",
        "no_alerts": "No alerts yet.",
        "no_alerts_logged": "No alerts logged yet.",
        "no_deliveries": "No deliveries for this event.",
        "no_hostgroups": "No host groups found.",
        "no_hosts": "No hosts found in this host group.",
        "no_services": "No services found.",
        "no_users": "No users in the database yet.",
        "not_selected": "Not selected yet",
        "notification_delivery_lead": "Track which notifications were created and who received them.",
        "notification_subscriptions": "notification subscriptions",
        "output": "Output",
        "password": "Bot password",
        "queue_file_size": "Queue file size",
        "quick_actions": "Quick actions",
        "raw_event": "Raw event",
        "roles_subscriptions": "Roles and subscriptions",
        "runtime_config": "Runtime config",
        "save": "Save",
        "select_alert": "Select an alert to see actions.",
        "selected_event_missing": "The selected event was not found.",
        "sent": "Sent",
        "service": "Service",
        "service_available": "Service reachable",
        "service_problem_count": "{count} service problem(s)",
        "smart_instructions": "Smart Notification Instructions",
        "source": "Source",
        "status": "Status",
        "system": "System",
        "telegram_users": "Telegram users",
        "to": "to",
        "type": "Type",
        "user": "User",
        "user_updated": "User was updated.",
        "users": "Users",
        "users_lead": "Roles and notification subscriptions are stored in SQLite, no longer in the config.",
        "users_management": "User management",
        "target": "Target",
        "time": "Time",
        "online_no_problems": "Online, no known problems",
        "with_problem": "with problems",
    },
}


def load_config() -> None:
    config.clear()
    config.read(CONFIG_PATH)


def web_setting(key: str, default: str) -> str:
    if not config.has_section("web"):
        return default
    return config.get("web", key, fallback=default)


def normalize_language(value: str | None) -> str:
    language = (value or "").replace("_", "-").split(",", 1)[0].split("-", 1)[0].lower()
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def current_language() -> str:
    if session.get("language") in SUPPORTED_LANGUAGES:
        return session["language"]
    return normalize_language(request.accept_languages.best_match(SUPPORTED_LANGUAGES))


def translate(key: str, **values) -> str:
    language = getattr(g, "language", DEFAULT_LANGUAGE)
    text = TRANSLATIONS.get(language, TRANSLATIONS[DEFAULT_LANGUAGE]).get(
        key, TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    )
    return text.format(**values) if values else text


@app.before_request
def set_request_language() -> None:
    g.language = current_language()


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
        "current_language": getattr(g, "language", DEFAULT_LANGUAGE),
        "supported_languages": SUPPORTED_LANGUAGES,
        "t": translate,
    }


def validate_csrf() -> None:
    token = session.get("csrf_token", "")
    submitted = request.form.get("csrf_token", "")
    if not token or not hmac.compare_digest(token, submitted):
        abort(400)


def safe_redirect_target(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("dashboard") if session.get("authenticated") else url_for("login")


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


def smart_instructions_path() -> Path:
    configured = (
        config.get("smart_notifications", "instructions_path", fallback="")
        if config.has_section("smart_notifications")
        else ""
    )
    if configured:
        return Path(configured)
    return Path("/etc/checkmk-telegram-plus/smart-notification-instructions.txt")


def load_smart_instructions() -> str:
    path = smart_instructions_path()
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return ""


def save_smart_instructions(value: str) -> None:
    path = smart_instructions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


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
        summary = (
            translate("host_problem")
            if problem_count == 0
            else translate("service_problem_count", count=problem_count)
        )
    else:
        summary = translate("online_no_problems")
    return {
        "hostname": hostname,
        "state": state,
        "badge_css": css,
        "badge_text": text,
        "service_problem_count": problem_count,
        "has_problem": has_problem,
        "summary": summary,
    }


@app.route("/language/<language>")
def set_language(language):
    session["language"] = normalize_language(language)
    return redirect(safe_redirect_target(request.args.get("next")))


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
        flash(translate("login_failed"), "danger")
        storage.add_audit(
            actor_type="web",
            action="web_login_failed",
            details=request.remote_addr or "",
        )
    return render_template(
        "login.html",
        title="Control Center",
        lead=translate("login_lead"),
        field_label=translate("password"),
        button_label=translate("login"),
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
        flash(translate("admin_login_failed"), "danger")
        storage.add_audit(
            actor_type="web",
            action="web_admin_login_failed",
            details=request.remote_addr or "",
        )
    return render_template(
        "login.html",
        title=translate("admin_login"),
        lead=translate("admin_login_lead"),
        field_label=translate("admin_password"),
        button_label=translate("admin_login_button"),
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
            notify_smart=request.form.get("notify_smart") == "on",
            active=request.form.get("active") == "on",
        )
        storage.add_audit(
            actor_type="web",
            action="user_updated",
            target=str(telegram_id),
            details=f"ip={request.remote_addr}",
        )
        flash(translate("user_updated"), "success")
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
            submitted_instructions = request.form.get("smart_instructions", "")
            if submitted_instructions != load_smart_instructions():
                save_smart_instructions(submitted_instructions)
                changed.append("smart_notifications.instructions")
            save_config()
        except OSError as exc:
            flash(translate("config_save_failed", error=exc), "danger")
        else:
            storage.add_audit(
                actor_type="web",
                action="config_updated",
                details=f"ip={request.remote_addr} changed={','.join(changed) or 'none'}",
            )
            if changed:
                flash(translate("config_saved"), "success")
            else:
                flash(translate("config_empty_changes"), "info")
            return redirect(url_for("admin_config"))
    return render_template(
        "admin_config.html",
        config_path=CONFIG_PATH,
        safe_config=config_form_data(),
        smart_instructions_path=smart_instructions_path(),
        smart_instructions=load_smart_instructions(),
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
