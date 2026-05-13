#!/bin/bash
set -Eeuo pipefail

REPO="deexno/checkmk-telegram-plus"
GITHUB_API="https://api.github.com/repos/$REPO"
DEFAULT_BRANCH="main"

error() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "==> $*"
}

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

usage() {
    cat <<EOF
Usage:
  sudo bash install.sh

Optional preseeded usage:
  sudo bash install.sh mysite 123456:ABC-DEF mySecretPassword

The installer asks for the CheckMK site name and version to install. Existing
configuration values are preserved by default. Missing required values such as
the Telegram API token and bot password are requested during the config review.
A branch install option is available for testing only.

This installer uses the split architecture:
  - Checkmk only receives a minimal notification adapter.
  - The app and Python dependencies are installed below /opt/checkmk-telegram-plus.
  - Runtime config/state/logs are stored below /etc, /var/lib, /var/log and /run.
EOF
}

read_from_tty() {
    local prompt=$1
    local value
    read -r -p "$prompt" value < /dev/tty
    printf '%s' "$value"
}

read_secret_from_tty() {
    local prompt=$1
    local value
    read -r -s -p "$prompt" value < /dev/tty
    echo > /dev/tty
    printf '%s' "$value"
}

is_placeholder_value() {
    case "$1" in
        ""|"<api_token>"|"<password_for_authentication>"|"<omd_site>"|"<state_dir>"|"<log_dir>"|"<run_dir>"|"<socket_path>"|"<bridge_socket_path>"|"<notification_queue>"|"<fallback_queue>"|"<openai_token>"|"YOUR-TOKEN")
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

prompt_value() {
    local label=$1
    local current=${2:-}
    local default_value=${3:-}
    local required=${4:-false}
    local value

    while true; do
        if [ -n "$current" ] && ! is_placeholder_value "$current"; then
            value=$(read_from_tty "$label [$current]: ")
            value=${value:-$current}
        elif [ -n "$default_value" ]; then
            value=$(read_from_tty "$label [$default_value]: ")
            value=${value:-$default_value}
        else
            value=$(read_from_tty "$label: ")
        fi

        if [ "$required" != "true" ] || ! is_placeholder_value "$value"; then
            printf '%s' "$value"
            return 0
        fi
        echo "This value is required and cannot be empty." > /dev/tty
    done
}

prompt_secret_value() {
    local label=$1
    local current=${2:-}
    local required=${3:-false}
    local value

    while true; do
        if [ -n "$current" ] && ! is_placeholder_value "$current"; then
            value=$(read_secret_from_tty "$label [configured, press Enter to keep]: ")
            value=${value:-$current}
        else
            value=$(read_secret_from_tty "$label: ")
        fi

        if [ "$required" != "true" ] || ! is_placeholder_value "$value"; then
            printf '%s' "$value"
            return 0
        fi
        echo "This value is required and cannot be empty." > /dev/tty
    done
}

cleanup() {
    if [ -n "${tmp_dir:-}" ] && [ -d "$tmp_dir" ]; then
        rm -rf "$tmp_dir"
    fi
}

trap cleanup EXIT

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

if [ "$EUID" -ne 0 ]; then
    error "Please run this installer as root, for example with sudo."
fi

if [ "$#" -gt 3 ]; then
    usage
    error "Too many arguments."
fi

if [ "$(uname -s)" != "Linux" ]; then
    error "Unsupported system. This installer currently supports Linux systems with systemd."
fi

if [ ! -r /dev/tty ]; then
    error "This installer needs an interactive terminal."
fi

programs=(curl python3 tar mktemp runuser sed systemctl getent id groupadd useradd usermod)

for program in "${programs[@]}"; do
    if ! command -v "$program" > /dev/null 2>&1; then
        error "Missing required program: $program. Please install it and run this installer again."
    fi
done

echo
echo "CheckMK Telegram Plus installer"
echo

omd_site=${1:-}
api_token=${2:-}
bot_password=${3:-}

while [ -z "$omd_site" ]; do
    omd_site=$(read_from_tty "CheckMK site name: ")
done

omd_site_dir="/omd/sites/$omd_site"
notification_plugin_dir="$omd_site_dir/local/share/check_mk/notifications"
site_share_dir="$omd_site_dir/local/share/checkmk-telegram-plus"

external_root="/opt/checkmk-telegram-plus"
app_dir="$external_root/app"
venv_dir="$external_root/venv"
app_user="checkmk-telegram-plus"
config_dir="/etc/checkmk-telegram-plus"
config_path="$config_dir/$omd_site.ini"
smart_instructions_path="$config_dir/smart-notification-instructions.txt"
state_root="/var/lib/checkmk-telegram-plus"
state_dir="$state_root/$omd_site"
log_dir="/var/log/checkmk-telegram-plus"
run_dir="/run/checkmk-telegram-plus"
socket_path="$run_dir/$omd_site.sock"
bridge_socket_path="$run_dir/$omd_site-bridge.sock"
notification_queue="$state_dir/notifications.queue"
fallback_queue="$state_dir/fallback/notifications.jsonl"
telegram_plus_service_name="checkmk-telegram-plus-$omd_site.service"
telegram_plus_bridge_service_name="checkmk-telegram-plus-bridge-$omd_site.service"
telegram_plus_web_service_name="checkmk-telegram-plus-web-$omd_site.service"

if [ ! -d "$omd_site_dir" ]; then
    error "The CheckMK site '$omd_site' does not exist at $omd_site_dir."
fi

if [ ! -d "$notification_plugin_dir" ]; then
    error "The CheckMK notification plugin directory does not exist: $notification_plugin_dir."
fi

tmp_dir=$(mktemp -d)
releases_file="$tmp_dir/releases.json"
archive_file="$tmp_dir/release.tar.gz"
source_dir="$tmp_dir/source"

info "Fetching the latest GitHub Releases..."
if ! curl -fsSL --retry 3 --connect-timeout 10 "$GITHUB_API/releases?per_page=3" -o "$releases_file"; then
    error "Could not fetch releases from GitHub. Please check your internet connection and try again."
fi

mapfile -t releases < <(
    python3 - "$releases_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception as exc:
    print(f"Could not parse GitHub release response: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(data, list):
    message = data.get("message", "Unexpected GitHub API response") if isinstance(data, dict) else "Unexpected GitHub API response"
    print(message, file=sys.stderr)
    sys.exit(1)

for release in data[:3]:
    tag = release.get("tag_name")
    name = release.get("name") or tag
    if tag:
        print(f"{tag}\t{name}")
PY
)

if [ "${#releases[@]}" -eq 0 ]; then
    error "No GitHub Releases were found. The installer will not install from the main branch."
fi

echo
echo "Available versions:"
for index in "${!releases[@]}"; do
    tag=${releases[$index]%%$'\t'*}
    name=${releases[$index]#*$'\t'}
    printf "  %d) %s" "$((index + 1))" "$tag"
    if [ "$name" != "$tag" ]; then
        printf " - %s" "$name"
    fi
    printf "\n"
done
branch_choice=$((${#releases[@]} + 1))
printf "  %d) %s branch (testing only)\n" "$branch_choice" "$DEFAULT_BRANCH"
echo

while true; do
    choice=$(read_from_tty "Choose the version to install [1-$branch_choice]: ")
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#releases[@]}" ]; then
        selected_release=${releases[$((choice - 1))]}
        selected_tag=${selected_release%%$'\t'*}
        selected_ref="$selected_tag"
        selected_version="$selected_tag"
        selected_source="release"
        break
    fi
    if [ "$choice" = "$branch_choice" ]; then
        selected_ref="$DEFAULT_BRANCH"
        selected_version="$DEFAULT_BRANCH"
        selected_source="branch"
        echo "Using the $DEFAULT_BRANCH branch. This is intended for testing only."
        break
    fi
    echo "Invalid selection. Please enter a number between 1 and $branch_choice."
done

info "Downloading $selected_source $selected_ref..."
if ! curl -fL --retry 3 --connect-timeout 10 "$GITHUB_API/tarball/$selected_ref" -o "$archive_file"; then
    error "Failed to download $selected_source $selected_ref from GitHub."
fi

mkdir -p "$source_dir"
if ! tar -xzf "$archive_file" --strip-components=1 -C "$source_dir"; then
    error "Failed to extract $selected_source $selected_ref."
fi

for required_file in \
    "$source_dir/resources/requirements.txt" \
    "$source_dir/resources/config.ini" \
    "$source_dir/resources/telegram_bot.py" \
    "$source_dir/resources/web_app.py" \
    "$source_dir/resources/fqueue.py" \
    "$source_dir/resources/checkmk-telegram-plus.service" \
    "$source_dir/resources/checkmk-telegram-plus-bridge.service" \
    "$source_dir/resources/checkmk-telegram-plus-web.service" \
    "$source_dir/checkmk/notifications/telegram_plus_notify_listener" \
    "$source_dir/checkmk/bridge/checkmk_bridge.py" \
    "$source_dir/src/checkmk_telegram_plus/api/notification_socket.py"
do
    if [ ! -f "$required_file" ]; then
        error "The selected $selected_source is missing required file: ${required_file#$source_dir/}"
    fi
done

timestamp=$(date +"%Y%m%d%H%M%S")
runuser_path=$(command -v runuser)
omd_site_sed=$(escape_sed_replacement "$omd_site")
selected_version_sed=$(escape_sed_replacement "$selected_version")
app_dir_sed=$(escape_sed_replacement "$app_dir")
venv_python_sed=$(escape_sed_replacement "$venv_dir/bin/python")
pythonpath_sed=$(escape_sed_replacement "$app_dir/src")
config_path_sed=$(escape_sed_replacement "$config_path")
run_dir_sed=$(escape_sed_replacement "$run_dir")
socket_path_sed=$(escape_sed_replacement "$socket_path")
bridge_socket_path_sed=$(escape_sed_replacement "$bridge_socket_path")
fallback_queue_sed=$(escape_sed_replacement "$fallback_queue")
runuser_path_sed=$(escape_sed_replacement "$runuser_path")
app_user_sed=$(escape_sed_replacement "$app_user")

info "Creating external service user and directories..."
if ! getent group "$app_user" > /dev/null; then
    groupadd --system "$app_user"
fi
if ! id -u "$app_user" > /dev/null 2>&1; then
    nologin_shell="/usr/sbin/nologin"
    if [ ! -x "$nologin_shell" ]; then
        nologin_shell="/bin/false"
    fi
    useradd --system --gid "$app_user" --home-dir /nonexistent --shell "$nologin_shell" "$app_user"
fi
usermod -a -G "$app_user" "$omd_site"
mkdir -p "$app_dir" "$venv_dir" "$config_dir" "$state_dir/fallback" "$log_dir" "$run_dir" "$site_share_dir/backups"
chown "$app_user:$app_user" "$state_root" "$run_dir"
chown -R "$app_user:$app_user" "$state_dir" "$log_dir"
chown "$omd_site:$app_user" "$state_dir" "$state_dir/fallback"
chmod 755 "$state_root"
chmod 750 "$log_dir"
chmod 2770 "$state_dir" "$state_dir/fallback"
if [ -f "$fallback_queue" ]; then
    chown "$omd_site:$app_user" "$fallback_queue"
    chmod 660 "$fallback_queue"
fi
chmod 2770 "$run_dir"
chown root:"$app_user" "$run_dir"

old_config="$site_share_dir/config.ini"
if [ -f "$old_config" ]; then
    old_backup="$site_share_dir/backups/config.ini.bak.$timestamp"
    cp -p "$old_config" "$old_backup"
    info "Backed up legacy site config to $old_backup"
fi

if [ -f "$config_path" ]; then
    config_backup="$config_path.bak.$timestamp"
    cp -p "$config_path" "$config_backup"
    info "Backed up external config to $config_backup"
elif [ -f "$old_config" ]; then
    cp -p "$old_config" "$config_path"
    info "Migrated legacy config from $old_config to $config_path"
else
    cp "$source_dir/resources/config.ini" "$config_path"
    info "Created new config at $config_path"
fi

eval "$(
    python3 - "$config_path" <<'PY'
import configparser
import shlex
import sys

config = configparser.RawConfigParser()
config.read(sys.argv[1])

fields = {
    "cfg_language": ("telegram_bot", "language"),
    "cfg_api_token": ("telegram_bot", "api_token"),
    "cfg_bot_password": ("telegram_bot", "password_for_authentication"),
    "cfg_allowed_users": ("telegram_bot", "allowed_users"),
    "cfg_admin_users": ("telegram_bot", "admin_users"),
    "cfg_notifications_loud": ("telegram_bot", "notifications_loud"),
    "cfg_notifications_silent": ("telegram_bot", "notifications_silent"),
    "cfg_notifications_smart": ("telegram_bot", "notifications_smart"),
    "cfg_openai_model": ("openai", "model"),
    "cfg_openai_token": ("openai", "token"),
    "cfg_smart_instructions_path": ("smart_notifications", "instructions_path"),
    "cfg_web_base_url": ("checkmk_web", "base_url"),
    "cfg_web_automation_user": ("checkmk_web", "automation_user"),
    "cfg_web_automation_secret": ("checkmk_web", "automation_secret"),
    "cfg_web_graph_count": ("checkmk_web", "graph_count"),
    "cfg_web_allow_legacy_url_auth": ("checkmk_web", "allow_legacy_url_auth"),
}

for variable, (section, key) in fields.items():
    value = config.get(section, key, fallback="")
    print(f"{variable}={shlex.quote(value)}")
PY
)"

if [ -n "$api_token" ]; then
    cfg_api_token="$api_token"
fi
if [ -n "$bot_password" ]; then
    cfg_bot_password="$bot_password"
fi

echo
echo "Configuration review for $config_path"
echo "Press Enter to keep existing values. Secrets are never printed."
echo

language=$(prompt_value "Bot language" "${cfg_language:-}" "en" true)
api_token=$(prompt_secret_value "Telegram API token" "${cfg_api_token:-}" true)
bot_password=$(prompt_secret_value "Bot password" "${cfg_bot_password:-}" true)
allowed_users=$(prompt_value "Allowed Telegram users" "${cfg_allowed_users:-}" "" false)
admin_users=$(prompt_value "Admin Telegram users" "${cfg_admin_users:-}" "" false)
notifications_loud=$(prompt_value "Loud notification targets" "${cfg_notifications_loud:-}" "" false)
notifications_silent=$(prompt_value "Silent notification targets" "${cfg_notifications_silent:-}" "" false)
notifications_smart=$(prompt_value "Smart notification targets" "${cfg_notifications_smart:-}" "" false)
openai_model=$(prompt_value "OpenAI model (optional)" "${cfg_openai_model:-}" "gpt-4o-mini" false)
openai_token=$(prompt_secret_value "OpenAI API token (optional)" "${cfg_openai_token:-}" false)

web_configured=false
if [ -n "${cfg_web_automation_user:-}" ] || { [ -n "${cfg_web_automation_secret:-}" ] && ! is_placeholder_value "${cfg_web_automation_secret:-}"; }; then
    web_configured=true
fi

if [ "$web_configured" = "true" ]; then
    review_web=$(read_from_tty "Review optional Checkmk Web graph export settings? [Y/n]: ")
    review_web=${review_web:-Y}
else
    review_web=$(read_from_tty "Configure optional Checkmk Web graph export settings now? [y/N]: ")
    review_web=${review_web:-N}
fi

web_base_url="${cfg_web_base_url:-http://127.0.0.1/$omd_site}"
if [ -z "$web_base_url" ] || [[ "$web_base_url" == *"<omd_site>"* ]]; then
    web_base_url="http://127.0.0.1/$omd_site"
fi
web_automation_user="${cfg_web_automation_user:-}"
web_automation_secret="${cfg_web_automation_secret:-}"
web_graph_count="${cfg_web_graph_count:-3}"
web_allow_legacy_url_auth="${cfg_web_allow_legacy_url_auth:-no}"

if [[ "$review_web" =~ ^[Yy]$ ]]; then
    web_base_url=$(prompt_value "Checkmk Web base URL" "$web_base_url" "http://127.0.0.1/$omd_site" false)
    web_automation_user=$(prompt_value "Checkmk automation user" "$web_automation_user" "" false)
    web_automation_secret=$(prompt_secret_value "Checkmk automation secret" "$web_automation_secret" false)
    web_graph_count=$(prompt_value "Number of graphs to fetch per service" "$web_graph_count" "3" false)
    web_allow_legacy_url_auth=$(prompt_value "Allow legacy URL auth for graph export? [yes/no]" "$web_allow_legacy_url_auth" "no" false)
fi

smart_instructions_path="${cfg_smart_instructions_path:-$smart_instructions_path}"
if [ -z "$smart_instructions_path" ] || [[ "$smart_instructions_path" == *"<"* ]]; then
    smart_instructions_path="$config_dir/smart-notification-instructions.txt"
fi

info "Updating external configuration..."
python3 - "$config_path" "$omd_site" "$api_token" "$bot_password" "$selected_version" "$state_dir" "$log_dir" "$run_dir" "$socket_path" "$bridge_socket_path" "$notification_queue" "$fallback_queue" "$language" "$allowed_users" "$admin_users" "$notifications_loud" "$notifications_silent" "$notifications_smart" "$openai_model" "$openai_token" "$smart_instructions_path" "$web_base_url" "$web_automation_user" "$web_automation_secret" "$web_graph_count" "$web_allow_legacy_url_auth" <<'PY'
import configparser
import secrets
import sys
from pathlib import Path

(
    config_path,
    site,
    api_token,
    bot_password,
    version,
    state_dir,
    log_dir,
    run_dir,
    socket_path,
    bridge_socket_path,
    notification_queue,
    fallback_queue,
    language,
    allowed_users,
    admin_users,
    notifications_loud,
    notifications_silent,
    notifications_smart,
    openai_model,
    openai_token,
    smart_instructions_path,
    web_base_url,
    web_automation_user,
    web_automation_secret,
    web_graph_count,
    web_allow_legacy_url_auth,
) = sys.argv[1:]

path = Path(config_path)
config = configparser.RawConfigParser()
config.read(path)

def ensure(section):
    if not config.has_section(section):
        config.add_section(section)

ensure("telegram_bot")
ensure("check_mk")
ensure("paths")
ensure("checkmk_web")
ensure("web")
ensure("smart_notifications")

config.set("telegram_bot", "language", language or "en")
config.set("telegram_bot", "allowed_users", allowed_users)
config.set("telegram_bot", "admin_users", admin_users)
config.set("telegram_bot", "notifications_loud", notifications_loud)
config.set("telegram_bot", "notifications_silent", notifications_silent)
config.set("telegram_bot", "notifications_smart", notifications_smart)

current_token = config.get("telegram_bot", "api_token", fallback="")
if not current_token or current_token == "<api_token>":
    config.set("telegram_bot", "api_token", api_token)
else:
    config.set("telegram_bot", "api_token", api_token or current_token)

current_password = config.get("telegram_bot", "password_for_authentication", fallback="")
if not current_password or current_password == "<password_for_authentication>":
    config.set("telegram_bot", "password_for_authentication", bot_password)
else:
    config.set("telegram_bot", "password_for_authentication", bot_password or current_password)

config.set("telegram_bot", "version", version)
config.set("check_mk", "site", site)

path_values = {
    "state_dir": state_dir,
    "log_dir": log_dir,
    "run_dir": run_dir,
    "socket_path": socket_path,
    "bridge_socket": bridge_socket_path,
    "notification_queue": notification_queue,
    "fallback_queue": fallback_queue,
}
for key, value in path_values.items():
    config.set("paths", key, value)

if not web_base_url or "<omd_site>" in web_base_url:
    web_base_url = f"http://127.0.0.1/{site}"

try:
    graph_count_int = int(web_graph_count)
    if graph_count_int < 1:
        raise ValueError
except ValueError:
    graph_count_int = 3

config.set("checkmk_web", "base_url", web_base_url)
config.set("checkmk_web", "automation_user", web_automation_user)
config.set("checkmk_web", "automation_secret", web_automation_secret)
config.set("checkmk_web", "graph_count", str(graph_count_int))
config.set("checkmk_web", "allow_legacy_url_auth", web_allow_legacy_url_auth or "no")

config.set("web", "host", config.get("web", "host", fallback="127.0.0.1"))
config.set("web", "port", config.get("web", "port", fallback="8183"))
current_web_admin_password = config.get("web", "admin_password", fallback="")
if (
    not current_web_admin_password
    or current_web_admin_password == "<admin_password>"
):
    current_web_admin_password = secrets.token_urlsafe(32)
config.set("web", "admin_password", current_web_admin_password)

ensure("openai")
config.set("openai", "model", openai_model or "gpt-4o-mini")
config.set("openai", "token", openai_token or "YOUR-TOKEN")
config.set(
    "smart_notifications",
    "instructions_path",
    smart_instructions_path
    or "/etc/checkmk-telegram-plus/smart-notification-instructions.txt",
)

if config.has_section("openai"):
    if config.get("openai", "token", fallback="") == "<openai_token>":
        config.set("openai", "token", "YOUR-TOKEN")

with path.open("w", encoding="utf-8") as handle:
    config.write(handle)
PY

chown "$app_user:$app_user" "$config_path"
chmod 640 "$config_path"

if [ ! -f "$smart_instructions_path" ]; then
    cp "$source_dir/resources/smart-notification-instructions.txt" "$smart_instructions_path"
    info "Created Smart Notification instructions at $smart_instructions_path"
fi
chown "$app_user:$app_user" "$smart_instructions_path"
chmod 640 "$smart_instructions_path"

info "Installing external app files..."
rm -rf "$app_dir.new"
mkdir -p "$app_dir.new/src"
cp "$source_dir/resources/telegram_bot.py" "$app_dir.new/telegram_bot.py"
cp "$source_dir/resources/web_app.py" "$app_dir.new/web_app.py"
cp "$source_dir/resources/fqueue.py" "$app_dir.new/fqueue.py"
cp -R "$source_dir/src/checkmk_telegram_plus" "$app_dir.new/src/"
if [ -d "$source_dir/resources/templates" ]; then
    cp -R "$source_dir/resources/templates" "$app_dir.new/"
fi
rm -rf "$app_dir.previous"
if [ -d "$app_dir" ] && [ "$(find "$app_dir" -mindepth 1 -maxdepth 1 | wc -l)" -gt 0 ]; then
    mv "$app_dir" "$app_dir.previous"
else
    rmdir "$app_dir" 2> /dev/null || true
fi
mv "$app_dir.new" "$app_dir"
chown -R root:root "$external_root"
chmod -R go-w "$external_root"

info "Creating or updating external Python virtual environment..."
if [ ! -x "$venv_dir/bin/python" ]; then
    python3 -m venv "$venv_dir"
fi
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install -r "$source_dir/resources/requirements.txt" --upgrade

info "Installing minimal Checkmk notification adapter..."
adapter_tmp="$tmp_dir/telegram_plus_notify_listener"
cp "$source_dir/checkmk/notifications/telegram_plus_notify_listener" "$adapter_tmp"
sed -i "s|<omd_site>|$omd_site_sed|g" "$adapter_tmp"
sed -i "s|<socket_path>|$socket_path_sed|g" "$adapter_tmp"
sed -i "s|<fallback_queue_path>|$fallback_queue_sed|g" "$adapter_tmp"
cp "$adapter_tmp" "$notification_plugin_dir/telegram_plus_notify_listener"
chown "$omd_site:$omd_site" "$notification_plugin_dir/telegram_plus_notify_listener"
chmod 755 "$notification_plugin_dir/telegram_plus_notify_listener"

info "Installing slim Checkmk bridge..."
mkdir -p "$site_share_dir/bridge"
bridge_script="$site_share_dir/bridge/checkmk_bridge.py"
cp "$source_dir/checkmk/bridge/checkmk_bridge.py" "$bridge_script"
sed -i "s|<omd_site>|$omd_site_sed|g" "$bridge_script"
sed -i "s|<bridge_socket_path>|$bridge_socket_path_sed|g" "$bridge_script"
chown -R "$omd_site:$omd_site" "$site_share_dir/bridge"
chmod 750 "$site_share_dir/bridge"
chmod 750 "$bridge_script"

cat > "$site_share_dir/adapter.ini" <<EOF
[adapter]
architecture = split
site = $omd_site
config = $config_path
socket = $socket_path
bridge_socket = $bridge_socket_path
fallback_queue = $fallback_queue
installed_version = $selected_version
installed_at = $timestamp
EOF
chown "$omd_site:$omd_site" "$site_share_dir/adapter.ini"
chmod 640 "$site_share_dir/adapter.ini"

info "Moving legacy Checkmk-site app files out of the active site path..."
legacy_dir="$site_share_dir/legacy-$timestamp"
mkdir -p "$legacy_dir"
shopt -s nullglob
for item in "$site_share_dir"/*; do
    base=$(basename "$item")
    case "$base" in
        config.ini|adapter.ini|backups|bridge|legacy-*)
            ;;
        *)
            mv "$item" "$legacy_dir/"
            ;;
    esac
done
shopt -u nullglob
chown -R "$omd_site:$omd_site" "$site_share_dir"
chmod -R go-rwx "$site_share_dir"
if [ "$(find "$legacy_dir" -mindepth 1 -maxdepth 1 | wc -l)" -eq 0 ]; then
    rmdir "$legacy_dir"
else
    info "Moved legacy files to $legacy_dir"
fi

info "Installing systemd services..."
service_tmp="$tmp_dir/checkmk-telegram-plus.service"
cp "$source_dir/resources/checkmk-telegram-plus.service" "$service_tmp"
sed -i "s|<omd_site>|$omd_site_sed|g" "$service_tmp"
sed -i "s|<app_user>|$app_user_sed|g" "$service_tmp"
sed -i "s|<app_dir>|$app_dir_sed|g" "$service_tmp"
sed -i "s|<venv_python>|$venv_python_sed|g" "$service_tmp"
sed -i "s|<pythonpath>|$pythonpath_sed|g" "$service_tmp"
sed -i "s|<config_path>|$config_path_sed|g" "$service_tmp"
sed -i "s|<run_dir>|$run_dir_sed|g" "$service_tmp"
cp "$service_tmp" "/etc/systemd/system/$telegram_plus_service_name"

bridge_service_tmp="$tmp_dir/checkmk-telegram-plus-bridge.service"
cp "$source_dir/resources/checkmk-telegram-plus-bridge.service" "$bridge_service_tmp"
sed -i "s|<runuser_path>|$runuser_path_sed|g" "$bridge_service_tmp"
sed -i "s|<omd_site>|$omd_site_sed|g" "$bridge_service_tmp"
sed -i "s|<app_user>|$app_user_sed|g" "$bridge_service_tmp"
sed -i "s|<run_dir>|$run_dir_sed|g" "$bridge_service_tmp"
sed -i "s|<site_python>|$(escape_sed_replacement "$omd_site_dir/bin/python3")|g" "$bridge_service_tmp"
sed -i "s|<bridge_script>|$(escape_sed_replacement "$bridge_script")|g" "$bridge_service_tmp"
cp "$bridge_service_tmp" "/etc/systemd/system/$telegram_plus_bridge_service_name"

web_service_tmp="$tmp_dir/checkmk-telegram-plus-web.service"
cp "$source_dir/resources/checkmk-telegram-plus-web.service" "$web_service_tmp"
sed -i "s|<omd_site>|$omd_site_sed|g" "$web_service_tmp"
sed -i "s|<app_user>|$app_user_sed|g" "$web_service_tmp"
sed -i "s|<app_dir>|$app_dir_sed|g" "$web_service_tmp"
sed -i "s|<venv_python>|$venv_python_sed|g" "$web_service_tmp"
sed -i "s|<pythonpath>|$pythonpath_sed|g" "$web_service_tmp"
sed -i "s|<config_path>|$config_path_sed|g" "$web_service_tmp"
cp "$web_service_tmp" "/etc/systemd/system/$telegram_plus_web_service_name"

info "Starting systemd service..."
if ! systemctl daemon-reload; then
    error "Failed to reload systemd."
fi
if ! systemctl enable "$telegram_plus_bridge_service_name"; then
    error "Failed to enable systemd service $telegram_plus_bridge_service_name."
fi
if ! systemctl enable "$telegram_plus_service_name"; then
    error "Failed to enable systemd service $telegram_plus_service_name."
fi
if ! systemctl enable "$telegram_plus_web_service_name"; then
    error "Failed to enable systemd service $telegram_plus_web_service_name."
fi
if ! systemctl restart "$telegram_plus_bridge_service_name"; then
    error "Failed to restart systemd service $telegram_plus_bridge_service_name. Check logs with: journalctl -u $telegram_plus_bridge_service_name"
fi
if ! systemctl restart "$telegram_plus_service_name"; then
    error "Failed to restart systemd service $telegram_plus_service_name. Check logs with: journalctl -u $telegram_plus_service_name"
fi
if ! systemctl restart "$telegram_plus_web_service_name"; then
    error "Failed to restart systemd service $telegram_plus_web_service_name. Check logs with: journalctl -u $telegram_plus_web_service_name"
fi

echo
echo "Installation completed successfully."
echo "Installed version: $selected_version"
echo "Architecture: split external app + minimal Checkmk adapter"
echo "App: $app_dir"
echo "Virtual environment: $venv_dir"
echo "Config: $config_path"
echo "State: $state_dir"
echo "Logs: $log_dir"
echo "Socket: $socket_path"
echo "Bridge socket: $bridge_socket_path"
echo "Web UI: http://127.0.0.1:8183"
echo "Rollback data: $site_share_dir/backups and any legacy-* directory"
echo "Next step: create or keep the CheckMK notification rule as described in the README."
