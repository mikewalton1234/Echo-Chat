# Hui Chat systemd deployment

This folder contains ready-to-edit Hui Chat project service files and an env template. The unit filenames intentionally stay `hui-*` for stable deployment compatibility; your public chat server name still comes from `server_config.json -> server_name`. You may edit the systemd `Description=` lines if you want local service output to show your custom server name.

## Recommended layout

- Project: `/opt/hui/hui-chat`
- Venv: `/opt/hui/hui-chat/.venv`
- Env file: `/etc/hui/hui-chat.env`
- User: `hui`

## Install steps (Arch)

### 1) Create a dedicated user

```bash
sudo useradd -r -s /usr/bin/nologin -d /opt/hui hui
```

### 2) Put Hui Chat under /opt

```bash
sudo mkdir -p /opt/hui
sudo chown -R hui:hui /opt/hui
```

Copy your repo contents to `/opt/hui/` and ensure:

- `/opt/hui/hui-chat` exists

### 3) Create venv + install deps

```bash
cd /opt/hui/hui-chat
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 4) Install Redis (optional but recommended)

```bash
sudo pacman -S redis
sudo systemctl enable --now redis
```

### 5) Install env file

```bash
sudo mkdir -p /etc/hui
sudo cp deploy/systemd/hui-chat.env.example /etc/hui/hui-chat.env
sudo chown root:hui /etc/hui/hui-chat.env
sudo chmod 640 /etc/hui/hui-chat.env
```

The service user must be able to read the EnvironmentFile, but the file should not be world-readable because it contains secrets. Edit `/etc/hui/hui-chat.env` and set real values.

### 6) Install a unit file

You have two options:

1) **Single-process dev-ish** (`python main.py`) — simplest.
2) **Production** (`Gunicorn gthread, one worker per instance`) — recommended.

#### Option A: python main.py

```bash
sudo cp deploy/systemd/hui-chat.service /etc/systemd/system/hui-chat.service
sudo systemctl daemon-reload
sudo systemctl enable --now hui
```

#### Option B: Gunicorn gthread, one worker per instance

Keep every Gunicorn process at one worker. If you scale with `hui-chat@5000`, `hui-chat@5001`, etc., use Redis Socket.IO queue plus sticky reverse-proxy routing.

```bash
sudo cp deploy/systemd/hui-chat-gunicorn.service /etc/systemd/system/hui-chat-gunicorn.service
sudo cp deploy/systemd/hui-chat-janitor.service /etc/systemd/system/hui-chat-janitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now hui-chat-gunicorn
sudo systemctl enable --now hui-chat-janitor
```

## Logs

```bash
journalctl -u hui -f
journalctl -u hui-chat-gunicorn -f
journalctl -u hui-chat-janitor -f
```

## Common tweaks

- If you installed Hui Chat somewhere else, update `WorkingDirectory=`, the Python path, the config path in each `ExecStartPre=`, and the config path in `ExecStart=`.
- Keep the generated/static `ExecStartPre=` checks. They catch bad config and unsafe Redis/Socket.IO topology before systemd starts the web process.
- If you do NOT want config persistence at all, keep `HUI_PERSIST_SECRETS=0` and remove `ReadWritePaths=.../server_config.json`.
- If you move upload, private upload, export, or instance folders outside the project root, add matching `ReadWritePaths=` entries or generate a settings-specific deployment kit.


## Multiple one-worker instances

For Socket.IO scaling, keep each Gunicorn server at one worker and run multiple instances with the template service:

```bash
sudo cp deploy/systemd/hui-chat@.service /etc/systemd/system/hui-chat@.service
sudo systemctl daemon-reload
sudo systemctl enable --now hui-chat@5000 hui-chat@5001
```

For 10 instances, start `hui-chat@5000` through `hui-chat@5009`, configure Redis Socket.IO queue, and put a sticky reverse proxy in front of those backend ports. Keep only one `hui-chat-janitor.service` active for the whole deployment.

Before enabling services, run the static checks from the project root:

```bash
python tools/deployment_ops_doctor.py
python tools/deployment_ops_deep_doctor.py
```
