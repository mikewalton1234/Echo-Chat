# Echo-Chat

**Echo-Chat** is a self-hosted chat server built with Flask and Socket.IO. It includes public rooms, custom rooms, private messages, group chats, WebRTC voice/webcam tools, encrypted file sharing, admin moderation tools, mobile-friendly screens.

Current build: **0.11.0-beta.309**

## What Echo-Chat Does

Echo-Chat is made to feel like a full chat app, not just a basic message board.

Features include:

* Public, private, invite-only, and custom chat rooms
* Direct/private messages
* Group chats with roles and member controls
* Friends, blocks, presence, alerts, and profiles
* WebRTC voice and webcam features
* Room radio and media controls
* Encrypted DM/group file sharing
* Torrent/magnet helper features
* Admin Panel with moderation, roles, audit logs, security tools, and test lab
* Mobile-friendly chat UI
* Setup wizard, deployment helpers, release checks, rollback docs, and operator handoff tools

## Tech Stack

* Python
* Flask
* Flask-SocketIO
* PostgreSQL
* JWT cookie authentication
* CSRF protection
* WebRTC signaling
* HTML/CSS/JavaScript frontend

## Status

Echo-Chat is currently in **beta**. It is being actively tested feature-by-feature before a public release.

Latest checked areas include:

* Authentication and account security
* Room and private-room behavior
* Direct messages and group chats
* Friends, blocks, profiles, and alerts
* File sharing and WebRTC media
* Admin Panel and Admin Test Lab
* Security, privacy, release packaging, and mobile UI

## Security Notes

Do **not** commit private runtime files such as:

* `.env`
* `server_config.json`
* database files
* private keys
* certificates
* uploaded user files
* backups
* logs
* production secrets

Use the included setup and release tools to check your configuration before running a public server.

## Basic Run Flow

Typical local setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --setup
python main.py
```

Production/public setup should be reviewed with the included config, release, and public-beta readiness checks before exposing the server online.

## Release Tools

Echo-Chat includes helper tools for:

* dependency checks
* config checks
* service smoke tests
* log sanity scans
* release integrity checks
* release reports
* package checksums
* rollback and admin handoff documentation

## License

Echo-Chat is intended to be released under the **PolyForm Noncommercial License 1.0.0**.

You may view, study, modify, and use the code for noncommercial purposes.

Commercial use is not allowed without permission.

See the `LICENSE` file for the full license text.
