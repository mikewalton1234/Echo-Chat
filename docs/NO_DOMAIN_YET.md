# Echo-Chat: no domain yet

This page is for admins who want to test Echo-Chat online later, but do not own a domain or stable HTTPS hostname yet.

## Safe choice right now

Use LAN testing until you have a real HTTPS address:

```json
{
  "hosting_mode": "no_domain_yet",
  "public_base_url": "",
  "https": false,
  "cookie_secure": false,
  "auto_allow_lan_origins": true
}
```

Run:

```bash
python main.py --setup
python main.py --hosting-help
python main.py --generate-proxy-config all
python main.py --public-beta-check
```

Without a real domain or HTTPS tunnel hostname, the reverse proxy generator writes LAN-only helper configs. It does not silently generate a fake public beta for `chat.example.com`.

## What not to do

Do not treat these as public-beta substitutes:

- `chat.example.com`, `example.com`, or `YOUR-REAL-DOMAIN`
- a bare public IP address as the user-facing login URL
- port-forwarding Echo-Chat's raw app port `5000` directly to the internet
- setting `cookie_secure=true` while users open the site over plain `http://`
- exposing PostgreSQL `5432` or Redis `6379` to the internet

Those choices make the server look public before the browser/security/proxy pieces are ready.

## Acceptable no-domain paths

You have three safe choices before buying a normal domain:

1. **LAN only**: phones and computers on the same Wi-Fi open `http://YOUR-LAN-IP:5000`.
2. **Private VPN/overlay only**: testers must join your private network first. Treat this like LAN testing, not public beta.
3. **HTTPS tunnel hostname**: a trusted tunnel provider gives you a stable HTTPS URL. Treat that URL like your public URL and run the public-beta readiness check.

For a tunnel hostname, use the exact HTTPS URL testers will open:

```json
{
  "hosting_mode": "public_beta",
  "public_base_url": "https://your-stable-tunnel-hostname",
  "allowed_origins": ["https://your-stable-tunnel-hostname"],
  "cors_allowed_origins": ["https://your-stable-tunnel-hostname"],
  "cookie_secure": true,
  "trust_proxy_headers": true,
  "proxy_fix_hops": 1,
  "auto_allow_lan_origins": false
}
```

Then run:

```bash
python main.py --public-beta-check
```

## What is required for real public beta

You need one of these:

1. A real domain or subdomain, such as `https://chat.yourdomain.com`, with DNS or Dynamic DNS pointing to your public server; or
2. A trusted tunnel provider that gives you a stable HTTPS hostname.

Then set:

```json
{
  "hosting_mode": "public_beta",
  "public_base_url": "https://chat.yourdomain.com",
  "allowed_origins": ["https://chat.yourdomain.com"],
  "cors_allowed_origins": ["https://chat.yourdomain.com"],
  "cookie_secure": true,
  "trust_proxy_headers": true,
  "proxy_fix_hops": 1,
  "auto_allow_lan_origins": false
}
```

Regenerate the proxy configs:

```bash
python main.py --generate-proxy-config all
python main.py --public-beta-check
```

## Dynamic DNS note

Dynamic DNS can keep a hostname pointed at your changing home/public IP, but it does not replace HTTPS. Use DDNS with Caddy/Nginx on ports 80/443 or with another TLS-terminating setup.

Validate DDNS settings first:

```bash
python main.py --dynamic-dns-check
```

Send one update only when the settings are correct:

```bash
python main.py --dynamic-dns-update
```

## Keep these private

Keep these private/local only:

- Echo-Chat raw app port: usually `5000`
- PostgreSQL: usually `5432`
- Redis: usually `6379`
- local secret/config files such as `server_config.json` and `.env`

For public beta, testers should open only the public HTTPS URL handled by Caddy, Nginx, or your tunnel provider.
