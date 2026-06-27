# Account creation rules

Echo-Chat account creation now uses one shared policy for public registration, admin-created users, password reset, account password change, setup-created admin users, and setup-created preload users.

## Username rules

- 3 to 24 characters.
- Lowercase normalized at registration.
- Letters, numbers, dot (`.`), underscore (`_`), and hyphen (`-`) only.
- Must start and end with a letter or number.
- Repeated separators such as `..`, `__`, or `--` are rejected.
- Built-in and admin-configured blocked terms are checked with simple obfuscation folding.

## Password rules

- 15 to 128 characters.
- A 20+ character passphrase is recommended when practical.
- Spaces, symbols, punctuation, uppercase letters, lowercase letters, numbers, and Unicode characters are accepted.
- Uppercase, number, and special-character composition rules are intentionally not forced.
- Obvious/common passwords, repetitive passwords, and passwords containing the username, email local part, or server name are rejected.
- Passwords are never silently truncated.

## Recovery PIN rules

- 4 to 8 digits.
- Required during setup-created admin accounts, public registration, Admin Panel user creation, and password reset when configured.
- Stored as a password hash, never as plaintext.
- Wrong reset PIN attempts use the configured lockout settings; hand-edited invalid settings are clamped to safe ranges.

## Rationale

This follows modern NIST/OWASP direction: prefer longer memorable passphrases, allow broad character sets, avoid forced composition rules, use a reasonable maximum length, and block common or context-derived secrets.

## Browser-side strength guidance

The register, reset-password, account-security, and admin create-user screens include a live password checklist. The meter is advisory and mirrors the server rules so users can fix problems before submitting, but the server remains the authority. The UI intentionally does not require a capital letter, number, or special character; it rewards longer passphrases and warns against common, repetitive, or context-derived passwords.


## Browser-side username guidance

The register screen and Admin Panel create-user card check `/api/username_available` as the username is typed. The check uses the same username format/style/blocklist rules as final registration and then verifies whether the normalized name already exists. This is only user guidance; public registration and admin creation repeat the authoritative validation on submit.
