<img src="src/checkmk-telegram-bot-banner.png" alt="Checkmk Telegram Plus" height="auto" />

# Checkmk Telegram Plus

Checkmk Telegram Plus connects Checkmk with Telegram. The bot sends automatic Checkmk alerts, lets you inspect hosts and services directly from Telegram, can trigger rechecks and acknowledgements, fetch service graphs, and optionally use AI features for alert help and Smart Notifications.

The goal is simple: understand monitoring problems faster when you are away from the Checkmk UI, reduce unnecessary clicks, and send important alerts to the right people.

> Note: This bot is intended for private Telegram chats, not for groups.

---

## Quick Start: Installation

The most important command:

```bash
curl -fsSL https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/refs/heads/main/install.sh | sudo bash
```

If you are already logged in as `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/refs/heads/main/install.sh | bash
```

You can optionally preseed the Checkmk site name, Telegram bot token and bot password:

```bash
curl -fsSL https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/refs/heads/main/install.sh | sudo bash -s -- <omd_site_name> <telegram_bot_token> <bot_password>
```

The installer still opens the interactive configuration review. Existing values are kept when you press Enter.

---

## Table Of Contents

- [Requirements](#requirements)
- [Installation Step By Step](#installation-step-by-step)
- [Create The Checkmk Notification Rule](#create-the-checkmk-notification-rule)
- [First Start In Telegram](#first-start-in-telegram)
- [Webapp And Telegram Mini App](#webapp-and-telegram-mini-app)
- [Feature Overview](#feature-overview)
- [Automatic Notifications](#automatic-notifications)
- [Smart Notifications With AI](#smart-notifications-with-ai)
- [Service Graphs](#service-graphs)
- [Admin Features](#admin-features)
- [Updates](#updates)
- [Configuration And Paths](#configuration-and-paths)
- [Uninstall](#uninstall)
- [Troubleshooting](#troubleshooting)
- [Support](#support)

---

## Examples

<img src="src/Screenshot_01.png" width="23%"></img> <img src="src/Screenshot_02.jpg" width="23%"></img> <img src="src/Screenshot_03.png" width="23%"></img> <img src="src/Screenshot_07.png" width="23%"></img>

---

## Requirements

### Checkmk

- Checkmk version 2.1.p25 or newer.
- An existing OMD site, for example `mysite`.
- Root or sudo access on the Checkmk server.

### Telegram

- A Telegram bot created with BotFather.
- The bot token, for example in the format `123456789:ABC...`.
- A bot login password. You set this password during installation.

### System Packages

The installer checks the required programs itself. The server should have these tools available:

- `curl`
- `python3`
- `tar`
- `mktemp`
- `runuser`
- `sed`
- `systemctl`

Depending on your distribution, you may also need the Python venv package, for example `python3-venv`.

---

## Installation Step By Step

### 1. Run The Installer

```bash
curl -fsSL https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/refs/heads/main/install.sh | sudo bash
```

The installer will:

- Ask for the Checkmk site name.
- Fetch the latest GitHub Releases and let you choose the version to install.
- Offer the `main` branch as an additional testing-only option.
- Create the external app structure below `/opt/checkmk-telegram-plus`.
- Install Python dependencies into a dedicated virtual environment.
- Create systemd services for the bot, bridge and webapp.
- Install only a small notification adapter into the Checkmk site.
- Check and repair permissions for the queue, fallback queue, logs and runtime sockets.
- Automatically migrate existing legacy installations where possible.

### 2. Review The Configuration

During installation, you will see a configuration review. The most important fields are:

| Field | Meaning |
| --- | --- |
| `Bot language` | Default bot language, for example `en` or `de`. |
| `Telegram API token` | Token from BotFather. |
| `Bot password` | Password users must enter to authenticate with the bot. |
| `Allowed Telegram users` | Can stay empty. Users are stored after successful authentication. |
| `Admin Telegram users` | Optional. Only these users can access admin features. |
| `OpenAI model` | Optional for AI features. The default is `gpt-4o-mini`. |
| `OpenAI API token` | Optional for AI features and Smart Notifications. |
| `Checkmk Web graph export settings` | Optional, but recommended for reliable service graph rendering. |

Secrets are not printed in clear text. If a value is already configured, press Enter to keep it.

### 3. Check The Services

After installation, three systemd services should be running:

```bash
omd_site_name=<omd_site_name>
systemctl status checkmk-telegram-plus-$omd_site_name.service
systemctl status checkmk-telegram-plus-bridge-$omd_site_name.service
systemctl status checkmk-telegram-plus-web-$omd_site_name.service
```

The webapp is available on port `8183` by default:

```text
http://<server-ip>:8183
```

From the server itself:

```text
http://127.0.0.1:8183
```

---

## Create The Checkmk Notification Rule

After installation, create a Checkmk notification rule so Checkmk can hand alerts to Telegram Plus.

1. Open Checkmk.
2. Go to the notification rules.
3. Create a new rule.
4. Select the Telegram Plus notification method.
5. Set the first parameter to one of these values:

| Parameter | Behavior |
| --- | --- |
| `notifications_loud` | Sends loud Telegram notifications. The device uses the normal notification sound or vibration. |
| `notifications_silent` | Sends silent Telegram notifications. The message appears in the chat, but without notification sound and usually without vibration. |
| `notifications_smart` | Sends the alert to the Smart Notification logic. The AI can decide whether the alert should be sent loud, sent silent, or suppressed. |

<img src="src/Screenshot_04.png" alt="Checkmk Notification Rule" height="auto" width="700" />

You can create multiple rules, for example a loud rule for critical production systems and a silent rule for less urgent systems. Alternatively, create one broad `notifications_smart` rule and let the Smart Notification logic filter duplicate, noisy or follow-up alerts.

Important: Users must enable notifications in the bot or webapp. Notifications are disabled by default.

---

## First Start In Telegram

### 1. Open The Bot

Open your Telegram bot and start it with:

```text
/start
```

or:

```text
/menu
```

### 2. Authenticate

The bot does not accept normal commands until you authenticate. Start authentication with:

```text
/authenticate
```

Then enter the bot password you configured during installation.

<br><img src="src/Screenshot_05.png" alt="Telegram Authentication" height="auto" width="600" />

After successful authentication, your Telegram user is stored and you can use the bot menus.

### 3. Enable Notifications

Open this menu in the bot:

```text
🔔 NOTIFICATION SETTINGS
```

There you can enable or disable these subscriptions for your own user:

- Loud Notifications
- Silent Notifications
- Smart Notifications

This setting only affects your Telegram user. Other users manage their own subscriptions independently.

<br><img src="src/Screenshot_06.png" alt="Notification Settings" height="auto" width="600" />

---

## Webapp And Telegram Mini App

Checkmk Telegram Plus includes a webapp in addition to the Telegram bot. It is not meant to replace Checkmk. It is a compact control center for common mobile and operational workflows.

### Open The Webapp

After installation, the webapp listens on port `8183` by default:

```text
http://<server-ip>:8183
```

Login uses the normal bot password. Administrative sections require a separate web admin password. Authorized admins can request that password from the Telegram admin menu:

```text
⚙️ ADMIN SETTINGS -> 🔑 GET WEB ADMIN PASSWORD
```

### What The Webapp Can Do

| Area | Function |
| --- | --- |
| Dashboard | Shows active users, queue size and the most recent alerts. |
| Monitoring | Browse host groups, open hosts and inspect services with their current state. |
| Alert Log | Shows received notifications, delivery status, errors and alert details. |
| Deliveries | Shows which Telegram users received an alert and whether delivery succeeded. |
| Alert Actions | Shows actions such as recheck, graph request, AI help, reminder or acknowledgement for each event. |
| User Management | Admins can enable or disable users, assign admin rights and manage notification subscriptions. |
| Audit Log | Shows logins, user changes, config changes and critical actions. |
| Config | Admins can edit the active runtime configuration and Smart Notification instructions. |

### Use The Webapp As A Telegram Mini App

You can also expose the webapp as a Telegram Mini App / Web App. It then appears directly inside your Telegram bot as a button and opens inside Telegram.

This is useful because:

- Users do not need to open a separate browser.
- Monitoring, alert history and user management are available next to the bot chat.
- The webapp feels like a compact mobile app on phones.
- The team gets one obvious entry point: open the Telegram bot, tap the button, use the control center.

Important: Telegram requires an externally reachable HTTPS URL. A local URL such as `http://127.0.0.1:8183` only works on the server itself and cannot be used as a Telegram Mini App for users.

Recommended setup:

```text
Telegram
  -> https://monitoring.example.com
  -> Reverse proxy with TLS
  -> http://127.0.0.1:8183
  -> Checkmk Telegram Plus webapp
```

Example Nginx reverse proxy:

```nginx
server {
    listen 443 ssl;
    server_name monitoring.example.com;

    ssl_certificate /etc/letsencrypt/live/monitoring.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/monitoring.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8183;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Then configure the button in Telegram:

1. Open `@BotFather`.
2. Select your bot with `/mybots`.
3. Open the bot settings.
4. Depending on the BotFather menu, choose `Menu Button`, `Configure Mini App`, or `/setmenubutton`.
5. Set the URL to your HTTPS address, for example `https://monitoring.example.com`.
6. Set the button text, for example `Monitoring` or `Control Center`.

Security note: The current webapp authenticates users with the bot password and protects admin actions with the separate web admin password. The Mini App integration is a convenient entry point inside Telegram, but it does not replace proper exposure controls. If the URL is reachable from the internet, use HTTPS, firewall rules, VPN or an upstream access control layer that fits your environment.

---

## Feature Overview

### Telegram Bot Menu

After authentication, the bot provides a menu for common monitoring tasks:

| Menu Item | Description |
| --- | --- |
| `⭕ GET HOST STATUS` | Queries the current state of a host. |
| `📃 GET SERVICES OF HOST` | Lists all services of a host with their current state. |
| `🔍 GET SERVICE DETAILS` | Shows details for a specific service, including output, state, last check time and metrics. |
| `🔥 GET ALL HOST PROBLEMS` | Lists current host problems from Checkmk. |
| `❗ GET ALL SERVICE PROBLEMS` | Lists current service problems from Checkmk. |
| `🔔 NOTIFICATION SETTINGS` | Enables or disables Loud, Silent and Smart Notifications for your own user. |
| `📉 GET SERVICE GRAPHS` | Fetches Checkmk service graphs and sends them as images in Telegram. |
| `🔄 RESCHEDULE CHECK` | Triggers a new check for a host or service. |
| `⚙️ ADMIN SETTINGS` | Opens administrative features if your user has admin rights. |

### Buttons In Automatic Alerts

Automatic alert messages can include additional inline buttons:

| Button | Description |
| --- | --- |
| `RECHECK` | Runs a new check and returns the updated state. |
| `GET SERVICE GRAPHS` | Sends matching Checkmk graphs for the affected service. |
| `HELP` | Asks the AI for a short explanation and possible troubleshooting steps. |
| `ACKNOWLEDGE` | Acknowledges the service problem in Checkmk. |
| `REMIND` | Creates a reminder so the alert appears again later in Telegram. |

These actions are written to the audit log so it remains clear who did what.

### Languages

The bot can translate replies into different languages. Admins can change the bot language from the admin menu. The webapp currently supports German and English and includes a language switcher in the navigation.

---

## Automatic Notifications

Checkmk passes alerts to the installed notification adapter. The adapter sends the notification to the external Telegram Plus app. If the app is temporarily unavailable, the adapter writes the alert into a fallback queue. Once the app is running again, it can drain that queue.

This prevents alerts from being lost just because the bot service was restarted briefly.

### Loud Notifications

`notifications_loud` is meant for important alerts. Telegram treats these messages like normal notifications. This is useful for:

- critical production systems
- host DOWN events
- important service CRITICAL events
- on-call duty

### Silent Notifications

`notifications_silent` is meant for less urgent information. The message arrives in the chat, but does not create a loud push notification. This is useful for:

- less critical systems
- warnings
- recovery messages
- informational messages that should not wake anyone up

### Per-User Subscriptions

Each user decides which notification types they want to receive. One admin can receive loud messages, while another user receives only silent messages or only Smart Notifications.

Admins can also manage these settings centrally in the webapp.

---

## Smart Notifications With AI

Smart Notifications are useful in environments where classic notification rules create too much noise.

If you use this parameter in a Checkmk notification rule:

```text
notifications_smart
```

the alert is not blindly sent to all Smart subscribers. Instead, it is enriched and evaluated first.

### What Smart Notifications Can Consider

The Smart Notification logic can use:

- the current Checkmk alert
- hostname, service, state change and plugin output
- Checkmk parent/child dependency context
- current host and service relationships
- recent notification history from the local SQLite database
- custom rules from `smart-notification-instructions.txt`
- the OpenAI Responses API when an API key is configured

### Possible Decisions

The AI can decide:

| Decision | Meaning |
| --- | --- |
| send loud | The alert is important enough for a loud notification. |
| send silent | The alert is relevant, but not urgent enough for a loud notification. |
| suppress | The alert is suppressed, for example because it looks like a duplicate, a follow-up failure or flapping. |

### Customize The Policy

The Smart Notification policy lives here:

```text
/etc/checkmk-telegram-plus/smart-notification-instructions.txt
```

Edit it directly:

```bash
omd_site_name=<omd_site_name>
nano /etc/checkmk-telegram-plus/smart-notification-instructions.txt
systemctl restart checkmk-telegram-plus-$omd_site_name.service
```

or use the webapp:

```text
Webapp -> Admin Login -> Config -> Smart Notification Instructions
```

### Enable OpenAI

Open the configuration:

```bash
omd_site_name=<omd_site_name>
nano /etc/checkmk-telegram-plus/$omd_site_name.ini
```

Set your API key in the `[openai]` section:

```ini
[openai]
model = gpt-4o-mini
token = YOUR_OPENAI_API_KEY
```

Restart the bot:

```bash
systemctl restart checkmk-telegram-plus-$omd_site_name.service
```

Note: AI output can be wrong or incomplete. Use it as troubleshooting assistance, not as the only decision source for critical systems.

---

## AI Help In The Bot

The AI feature has two main areas.

### HELP Button On Alerts

Automatic alert messages can include a `HELP` button. When you press it, the AI creates a short assessment:

- What might have happened?
- What does the service output probably mean?
- Which first troubleshooting steps could make sense?
- Which common causes match the error pattern?

<br>
<img src="src/Screenshot_16.png" alt="AI Help Button" height="auto" width="350" /></img><br>
<img src="src/Screenshot_17.png" alt="AI Help Answer" height="auto" width="350" /></img>

### Free AI Chat

The bot can also answer general questions, for example:

- questions about Checkmk
- Linux or network troubleshooting questions
- first analysis ideas for service outputs
- general IT questions

<br>
<img src="src/Screenshot_18.png" alt="AI Chat" height="auto" width="350" /></img><br>
<img src="src/Screenshot_19.png" alt="AI Chat Answer" height="auto" width="350" /></img>

---

## Service Graphs

Checkmk Telegram Plus can fetch service graphs from Checkmk and send them in Telegram. This helps you see whether a problem appeared suddenly, developed slowly, or keeps repeating.

The bot tries several methods:

1. Checkmk's internal graph renderer, if the installed Checkmk version still provides it.
2. Checkmk Web notification graph endpoint `ajax_graph_images.py`.
3. Checkmk Web PNG export endpoint `graph_image.py`.

Recommended configuration:

```bash
omd_site_name=<omd_site_name>
nano /etc/checkmk-telegram-plus/$omd_site_name.ini
```

```ini
[checkmk_web]
base_url = http://127.0.0.1/<omd_site_name>
automation_user = telegram_plus
automation_secret = YOUR_AUTOMATION_SECRET
graph_count = 3
allow_legacy_url_auth = no
```

The automation user must be allowed to see the requested hosts and services and query graph data. On newer Checkmk versions, the role permission `Query metric backend from custom graph editor` may be required.

Graph support is optional. If graphs are not available, the bot, alerts and bridge continue running.

---

## Admin Features

Admin features are only intended for users configured as admins in the config or webapp.

### Configure Admins

Open the configuration:

```bash
omd_site_name=<omd_site_name>
nano /etc/checkmk-telegram-plus/$omd_site_name.ini
```

The `[telegram_bot]` section contains `admin_users`:

```ini
[telegram_bot]
allowed_users = alice (123456789),bob (987654321),
admin_users = alice (123456789),
```

Restart the bot:

```bash
systemctl restart checkmk-telegram-plus-$omd_site_name.service
```

You can also assign admin rights in the webapp:

```text
Webapp -> Admin Login -> Users -> enable Admin -> Save
```

### Telegram Admin Menu

The Telegram admin menu includes:

| Function | Description |
| --- | --- |
| `📖 GET LOGS` | Shows recent bot logs in Telegram. |
| `🇩🇪 CHANGE LANGUAGE` | Changes the bot language. |
| `🔓 GET PASSWORD` | The bot password is no longer displayed in clear text for security reasons. |
| `🔒 CHANGE PASSWORD` | Changes the bot password. |
| `👥 LIST USERS` | Lists known Telegram users, roles and notification subscriptions. |
| `🗑️ DELETE USERS` | Removes users from the bot database. |
| `⬆️ CHECK FOR UPDATES` | Checks whether a newer version is available. |
| `🔔 LIST NOTIFY QUEUE` | Shows the current notification queue. |
| `✴ GET OMD STATUS` | Gets the OMD status of the Checkmk site. |
| `⬆ START OMD SERVICES` | Starts OMD services of the Checkmk site. |
| `⬇ STOP OMD SERVICES` | Stops OMD services of the Checkmk site. |
| `🔑 GET WEB ADMIN PASSWORD` | Shows the separate web admin password. |

### Audit

Critical actions are logged. This includes:

- web logins
- failed logins
- user changes
- config changes
- rechecks
- graph requests
- acknowledgements
- AI help requests
- Smart Notification decisions

The audit log is visible in the webapp.

---

## Architecture

Checkmk Telegram Plus uses a split architecture.

### Why?

Checkmk itself should load as few external dependencies as possible. Therefore, only a small notification adapter is installed inside the Checkmk site. The actual app with Telegram, Flask, OpenAI and other Python dependencies runs outside the Checkmk site.

### Components

| Component | Responsibility |
| --- | --- |
| Checkmk notification adapter | Collects `NOTIFY_*` variables and sends them to the external app. |
| External Telegram app | Handles alerts, bot commands, AI features and Telegram delivery. |
| Checkmk bridge | Runs allowed Checkmk operations as the site user. |
| Webapp | Provides dashboard, monitoring, alert log, user admin, audit and config pages. |
| SQLite state | Stores users, notification history, deliveries and audit entries. |
| Fallback queue | Buffers notifications while the external app is temporarily unavailable. |

More details are available in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Updates

To update, run the same installation command again:

```bash
curl -fsSL https://raw.githubusercontent.com/deexno/checkmk-telegram-plus/refs/heads/main/install.sh | sudo bash
```

The installer:

- shows the latest releases
- lets you choose the target version
- backs up existing configuration files
- migrates legacy installations
- keeps existing values when you press Enter
- restarts the bot, bridge and webapp

If fallback queue permissions or group memberships cause problems after an upgrade, rerun the installer and restart the Checkmk site so already-running Checkmk processes pick up the new group membership.

---

## Configuration And Paths

Important paths:

```text
/opt/checkmk-telegram-plus/app
/opt/checkmk-telegram-plus/venv
/etc/checkmk-telegram-plus/<omd_site_name>.ini
/etc/checkmk-telegram-plus/smart-notification-instructions.txt
/var/lib/checkmk-telegram-plus/<omd_site_name>
/var/log/checkmk-telegram-plus
/run/checkmk-telegram-plus/<omd_site_name>.sock
/run/checkmk-telegram-plus/<omd_site_name>-bridge.sock
```

Important services:

```text
checkmk-telegram-plus-<omd_site_name>.service
checkmk-telegram-plus-bridge-<omd_site_name>.service
checkmk-telegram-plus-web-<omd_site_name>.service
```

Show logs:

```bash
omd_site_name=<omd_site_name>
journalctl -u checkmk-telegram-plus-$omd_site_name.service -f
journalctl -u checkmk-telegram-plus-bridge-$omd_site_name.service -f
journalctl -u checkmk-telegram-plus-web-$omd_site_name.service -f
```

Edit configuration:

```bash
omd_site_name=<omd_site_name>
nano /etc/checkmk-telegram-plus/$omd_site_name.ini
systemctl restart checkmk-telegram-plus-$omd_site_name.service
systemctl restart checkmk-telegram-plus-web-$omd_site_name.service
```

---

## Uninstall

### 1. Stop Services

```bash
omd_site_name=<omd_site_name>
systemctl stop checkmk-telegram-plus-$omd_site_name.service
systemctl stop checkmk-telegram-plus-bridge-$omd_site_name.service
systemctl stop checkmk-telegram-plus-web-$omd_site_name.service
```

### 2. Remove systemd Files

```bash
rm -f /etc/systemd/system/checkmk-telegram-plus-$omd_site_name.service
rm -f /etc/systemd/system/checkmk-telegram-plus-bridge-$omd_site_name.service
rm -f /etc/systemd/system/checkmk-telegram-plus-web-$omd_site_name.service
systemctl daemon-reload
```

### 3. Remove Checkmk Notification Rules

Delete all Checkmk notification rules that use the Telegram Plus adapter.

### 4. Remove Files

```bash
rm -f /omd/sites/$omd_site_name/local/share/check_mk/notifications/telegram_plus_notify_listener
rm -rf /omd/sites/$omd_site_name/local/share/checkmk-telegram-plus
rm -f /etc/checkmk-telegram-plus/$omd_site_name.ini
rm -rf /var/lib/checkmk-telegram-plus/$omd_site_name
```

Only remove these paths if no other Checkmk site uses this installation:

```bash
rm -rf /opt/checkmk-telegram-plus
rm -rf /var/log/checkmk-telegram-plus
```

---

## Troubleshooting

The detailed troubleshooting guide is here:

<b><a href="TROUBLESHOOTING.md">TROUBLESHOOTING GUIDE</a></b>

Useful first checks:

```bash
omd_site_name=<omd_site_name>
systemctl status checkmk-telegram-plus-$omd_site_name.service
systemctl status checkmk-telegram-plus-bridge-$omd_site_name.service
systemctl status checkmk-telegram-plus-web-$omd_site_name.service
journalctl -u checkmk-telegram-plus-$omd_site_name.service -n 100
```

If notifications do not arrive:

- Is the Checkmk notification rule active?
- Is the first parameter correct, for example `notifications_loud`?
- Did the Telegram user authenticate with `/authenticate`?
- Are notification settings enabled for this user?
- Is the bot service running?
- Are there entries in the fallback queue?

If graphs do not work:

- Is `[checkmk_web]` configured correctly?
- Can the automation user see the host and service in Checkmk?
- Does the user have the required permissions for graph data?
- Is `base_url = http://127.0.0.1/<omd_site_name>` reachable locally?

---

## Mentions And Articles About The Bot

[TUTONAUT](https://www.tutonaut.de/checkmk-x-telegram-benachrichtigungen-status-spass/)<br>
[DEVINSIDER](https://www.dev-insider.de/kundenservice-verbesserung-mit-chatbots-ki-a-2ccfbe16571dd9071bdb096199ea82b7/)

---

## Support

<a href="https://www.buymeacoffee.com/deexno" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>
<a href="https://www.paypal.com/paypalme/deexno" target="_blank"><img src="https://img.shields.io/badge/Support me-00457C?style=for-the-badge&logo=paypal&logoColor=white" height="41" /></a>

---

## Personalized AI Chatbots

In addition to the features described here, we also develop personalized AI chatbots tailored to specific requirements. These custom solutions can provide more precise and context-aware assistance for support, monitoring and other specialized use cases.

More information and example projects: [https://www.dexdot.it/](https://www.dexdot.it/chatbots-kundenservice-automatisieren-suedtirol/)
