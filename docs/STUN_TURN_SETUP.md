# STUN/TURN setup for webcam, voice, and P2P files

Echo-Chat uses browser WebRTC for room webcam, voice, and P2P file transfer signaling. WebRTC needs ICE servers so browsers can discover how peers can reach each other.

## Practical rule

- **STUN** is enough for many same-LAN and simple home-network tests.
- **TURN** is the compatibility relay for real internet tests, cellular networks, hotel Wi-Fi, school/corporate firewalls, and strict NAT.
- If users can see camera permission prompts but peers stay stuck at connecting, missing TURN is one of the first things to check.

## Setup wizard helper

Open setup and go to **Voice and WebRTC**. The wizard accepts either comma-separated URLs or JSON RTCIceServer objects:

```text
stun:stun.l.google.com:19302, turn:turn.example.com:3478, turns:turn.example.com:5349
```

or:

```json
[
  {"urls": "stun:stun.l.google.com:19302"},
  {"urls": "turn:turn.example.com:3478", "username": "user", "credential": "password"},
  {"urls": "turns:turn.example.com:5349", "username": "user", "credential": "password"}
]
```

Leave **Voice/webcam ICE servers** blank when it should use the same list as P2P/WebRTC file transfer.

## Admin Panel helper

Admin Panel → **Echo Voice** → **STUN/TURN connectivity** shows the current ICE summary and lets an admin paste the same comma-separated URLs or JSON. The admin response redacts saved TURN credentials so the panel does not display secrets after saving.

## Environment variables

Production should prefer environment variables or a secret manager instead of writing long-lived TURN credentials to `server_config.json`.

```bash
ECHOCHAT_WEBRTC_ICE_SERVERS_JSON='[{"urls":"stun:stun.l.google.com:19302"},{"urls":"turn:turn.example.com:3478","username":"user","credential":"password"}]'
ECHOCHAT_VOICE_ICE_SERVERS_JSON=''
```

Simpler TURN-only form:

```bash
ECHOCHAT_TURN_URLS='turn:turn.example.com:3478,turns:turn.example.com:5349'
ECHOCHAT_TURN_USERNAME='user'
ECHOCHAT_TURN_CREDENTIAL='password'
```

When `ECHOCHAT_TURN_URLS` is used, Echo-Chat applies it to both P2P files and voice/webcam unless a more specific JSON variable is set.

You can also save only the TURN URLs in setup/admin and keep the username/password in environment variables:

```bash
ECHOCHAT_TURN_USERNAME='user'
ECHOCHAT_TURN_CREDENTIAL='password'
```

Echo-Chat applies those env credentials to saved TURN URLs before sending ICE config to the browser. Setup and the Admin Panel now block TURN URLs that still have no username/credential after env overrides are considered.

## coturn notes

A normal coturn deployment usually exposes UDP/TCP 3478 and optionally TLS TURN on 5349. For production, use short-lived TURN REST credentials when possible instead of a permanent password. At the network level, block internal/private relay destinations, rate-limit allocations, and isolate the TURN server from private infrastructure.

## Echo-Chat saved keys

Current canonical keys:

- `p2p_ice_servers`
- `voice_ice_servers`

Old aliases such as `p2p_ice`, `webrtc_ice_servers`, and `ice_servers` are still imported for backward compatibility, but new setup/admin saves only the canonical keys.
