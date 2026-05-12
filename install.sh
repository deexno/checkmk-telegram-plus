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

Optional non-interactive usage:
  sudo bash install.sh mysite 123456:ABC-DEF mySecretPassword

The installer asks for the CheckMK site name, Telegram API token, bot password,
and version to install. A branch install option is available for testing only.
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

programs=(curl python3 tar mktemp runuser pip3 sed systemctl)

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

while [ -z "$api_token" ]; do
    api_token=$(read_secret_from_tty "Telegram API token: ")
done

while [ -z "$bot_password" ]; do
    bot_password=$(read_secret_from_tty "Bot password: ")
done

omd_site_dir="/omd/sites/$omd_site"
telegram_plus_dir="$omd_site_dir/local/share/checkmk-telegram-plus"
telegram_plus_service_name="checkmk-telegram-plus-$omd_site.service"
notification_plugin_dir="$omd_site_dir/local/share/check_mk/notifications"

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
    "$source_dir/resources/fqueue.py" \
    "$source_dir/resources/checkmk-telegram-plus.service" \
    "$source_dir/resources/telegram_plus_notify_listener"
do
    if [ ! -f "$required_file" ]; then
        error "The selected $selected_source is missing required file: ${required_file#$source_dir/}"
    fi
done

runuser_path=$(command -v runuser)
omd_site_sed=$(escape_sed_replacement "$omd_site")
api_token_sed=$(escape_sed_replacement "$api_token")
bot_password_sed=$(escape_sed_replacement "$bot_password")
telegram_plus_dir_sed=$(escape_sed_replacement "$telegram_plus_dir")
runuser_path_sed=$(escape_sed_replacement "$runuser_path")
selected_version_sed=$(escape_sed_replacement "$selected_version")

info "Installing Python dependencies..."
mkdir -p "$telegram_plus_dir"
if ! pip3 install --target="$telegram_plus_dir" -r "$source_dir/resources/requirements.txt" --upgrade; then
    error "Failed to install Python dependencies. Please check the pip3 output above."
fi
rm -rf "$telegram_plus_dir"/httpx*

info "Preparing configuration..."
sed -i "s|<omd_site>|$omd_site_sed|g" "$source_dir"/resources/*
sed -i "s|<api_token>|$api_token_sed|g" "$source_dir"/resources/*
sed -i "s|<password_for_authentication>|$bot_password_sed|g" "$source_dir"/resources/*
sed -i "s|<telegram_plus_dir>|$telegram_plus_dir_sed|g" "$source_dir"/resources/*
sed -i "s|<runuser_path>|$runuser_path_sed|g" "$source_dir"/resources/*

cp -n "$source_dir/resources/config.ini" "$telegram_plus_dir/config.ini"
grep -qF -- "version" "$telegram_plus_dir/config.ini" || sed -i "s|\[telegram_bot\]|\[telegram_bot\]\nversion = v0.0.0|g" "$telegram_plus_dir/config.ini"
sed -i "s|.*version.*|version = $selected_version_sed|g" "$telegram_plus_dir/config.ini"

info "Installing bot files..."
cp "$source_dir/resources/telegram_bot.py" "$telegram_plus_dir/telegram_bot.py"
cp "$source_dir/resources/fqueue.py" "$telegram_plus_dir/fqueue.py"
cp "$source_dir/resources/checkmk-telegram-plus.service" "/etc/systemd/system/$telegram_plus_service_name"

chown -R "$omd_site:$omd_site" "$telegram_plus_dir"
chmod -R 755 "$telegram_plus_dir"

info "Installing CheckMK notification plugin..."
mkdir -p "$omd_site_dir/tmp/telegram_plus"
rm -f "$omd_site_dir/tmp/telegram_plus/notifications.queue"
cp "$source_dir/resources/telegram_plus_notify_listener" "$notification_plugin_dir/telegram_plus_notify_listener"
chown "$omd_site:$omd_site" "$notification_plugin_dir/telegram_plus_notify_listener"
chmod 755 "$notification_plugin_dir/telegram_plus_notify_listener"

info "Starting systemd service..."
if ! systemctl daemon-reload; then
    error "Failed to reload systemd."
fi
if ! systemctl enable "$telegram_plus_service_name"; then
    error "Failed to enable systemd service $telegram_plus_service_name."
fi
if ! systemctl restart "$telegram_plus_service_name"; then
    error "Failed to restart systemd service $telegram_plus_service_name. Check the service logs with: journalctl -u $telegram_plus_service_name"
fi

echo
echo "Installation completed successfully."
echo "Installed version: $selected_version"
echo "Next step: create the CheckMK notification rule as described in the README."
