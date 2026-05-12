# Split Architecture

Checkmk Telegram Plus now separates the Checkmk integration from the Python
application runtime.

## Components

### Checkmk adapter

The only active file inside the Checkmk notification plugin path is:

```text
/omd/sites/<site>/local/share/check_mk/notifications/telegram_plus_notify_listener
```

The adapter uses only the Python standard library. It collects bounded
`NOTIFY_*` environment variables, builds a JSON notification payload and sends it
to the external app through a Unix domain socket:

```text
/run/checkmk-telegram-plus/<site>.sock
```

If the socket is unavailable, the adapter appends the payload to:

```text
/var/lib/checkmk-telegram-plus/<site>/fallback/notifications.jsonl
```

The adapter does not import Telegram, OpenAI, Flask/FastAPI or other large
third-party dependencies.

### Checkmk bridge

Checkmk reads, graph rendering and commands are handled by a separate slim
bridge installed below the Checkmk site:

```text
/omd/sites/<site>/local/share/checkmk-telegram-plus/bridge/checkmk_bridge.py
```

The bridge is started as the Checkmk site user by:

```text
checkmk-telegram-plus-bridge-<site>.service
```

It exposes a local Unix domain socket:

```text
/run/checkmk-telegram-plus/<site>-bridge.sock
```

The bridge allowlists typed operations such as listing hostgroups, service
details, graph rendering, `cmk --check`, OMD status/start/stop and service
acknowledgement. It does not expose a generic shell or arbitrary Livestatus
query endpoint.

### External app

The application runs outside the Checkmk site tree:

```text
/opt/checkmk-telegram-plus/app/
/opt/checkmk-telegram-plus/venv/
```

Configuration, state, logs and runtime sockets are stored separately:

```text
/etc/checkmk-telegram-plus/<site>.ini
/var/lib/checkmk-telegram-plus/<site>/
/var/log/checkmk-telegram-plus/
/run/checkmk-telegram-plus/
```

The current implementation keeps the existing Telegram bot flows intact. The
systemd service starts the app as the dedicated `checkmk-telegram-plus` system
user. The external app does not import Checkmk internals and does not execute
Checkmk commands directly. It communicates with the bridge over the local Unix
socket. Third-party dependencies are installed into the external venv, not into
the Checkmk site.

## Notification Flow

```text
Checkmk notification rule
  -> telegram_plus_notify_listener
  -> Unix domain socket
  -> external app socket endpoint
  -> compatibility notification queue
  -> existing Telegram notification flow
```

If the app is unavailable:

```text
Checkmk notification rule
  -> telegram_plus_notify_listener
  -> fallback JSONL queue
  -> external app drains fallback after restart
  -> existing Telegram notification flow
```

Payloads include an `event_id`. The external queue writer uses that ID to avoid
adding duplicate events when the same payload is delivered more than once.

## Checkmk Command Flow

```text
Telegram command / button
  -> external app
  -> Checkmk bridge Unix socket
  -> typed allowlisted Checkmk operation
  -> bridge response
  -> Telegram response
```

This keeps Telegram, OpenAI and future web dependencies out of the Checkmk
runtime while preserving existing bot behavior.

## Upgrade And Rollback

The installer backs up existing configs before writing:

```text
/omd/sites/<site>/local/share/checkmk-telegram-plus/backups/config.ini.bak.<timestamp>
/etc/checkmk-telegram-plus/<site>.ini.bak.<timestamp>
```

Legacy files in the Checkmk site app directory are moved to:

```text
/omd/sites/<site>/local/share/checkmk-telegram-plus/legacy-<timestamp>/
```

Rollback consists of stopping the new service, restoring the legacy files and
config from those backups, and reinstalling the old service file from the legacy
directory or previous release package.
