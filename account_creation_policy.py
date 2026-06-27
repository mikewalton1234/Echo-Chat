from __future__ import annotations

import re
from typing import Iterable, Any

from registration_name_policy import username_policy_summary as _registration_username_policy_summary
from registration_name_policy import USERNAME_MIN_LENGTH, USERNAME_MAX_LENGTH

PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128
PASSWORD_RECOMMENDED_LENGTH = 20
RECOVERY_PIN_MIN_LENGTH = 4
RECOVERY_PIN_MAX_LENGTH = 8
RECOVERY_PIN_DEFAULT_MAX_ATTEMPTS = 5
RECOVERY_PIN_DEFAULT_LOCK_MINUTES = 15
PASSWORD_RESET_DEFAULT_TOKEN_MINUTES = 15
PASSWORD_RESET_DEFAULT_DAILY_LIMIT = 3
PASSWORD_RESET_DEFAULT_MAX_ACTIVE_TOKENS = 3


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPEATED_SEPARATORS_RE = re.compile(r"[._-]{2,}")

_COMMON_WEAK_PASSWORDS = {
    "password",
    "password1",
    "password12",
    "password123",
    "password1234",
    "passw0rd",
    "qwerty",
    "qwerty123",
    "letmein",
    "welcome",
    "welcome1",
    "admin",
    "admin123",
    "administrator",
    "changeme",
    "defaultpassword",
    "echochat",
    "echochat123",
    "iloveyous",
    "abc123",
    "12345678",
    "123456789",
    "123456789012345",
}

# These are not composition requirements. They are narrow server-side guards for
# passwords that satisfy the length rule only by repeating/digit-padding obvious
# weak material. The browser meter mirrors this shape, but this server function
# remains authoritative for all account/password-write paths.
_WEAK_PASSWORD_SEEDS = tuple(
    sorted(
        {
            "admin",
            "administrator",
            "changeme",
            "defaultpassword",
            "echochat",
            "iloveyou",
            "letmein",
            "mikeschatserver",
            "mikeserver",
            "qwerty",
            "welcome",
        },
        key=len,
        reverse=True,
    )
)
_WEAK_SEQUENCE_SUBSTRINGS = (
    "abcdefghijklmnopqrstuvwxyz",
    "zyxwvutsrqponmlkjihgfedcba",
    "qwertyuiop",
    "poiuytrewq",
    "asdfghjkl",
    "lkjhgfdsa",
    "zxcvbnm",
    "mnbvcxz",
    "1234567890",
    "0987654321",
)
_LEET_TRANSLATION = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


PASSWORD_COMMON_WEAK = tuple(sorted(_COMMON_WEAK_PASSWORDS))


def password_policy_summary() -> str:
    return (
        f"Password must be {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters. "
        f"A {PASSWORD_RECOMMENDED_LENGTH}+ character passphrase is recommended when practical. "
        "Spaces and symbols are allowed; uppercase/special characters are not forced."
    )


def password_policy_title() -> str:
    return password_policy_summary()


def password_policy_metadata() -> dict[str, Any]:
    """Return browser/template-safe password policy metadata.

    Server validation remains authoritative, but all account-creation and
    password-change surfaces should use this metadata for minlength, maxlength,
    help text, and advisory meters so UI hints cannot drift from the server rule.
    """
    return {
        "min_length": PASSWORD_MIN_LENGTH,
        "max_length": PASSWORD_MAX_LENGTH,
        "recommended_length": PASSWORD_RECOMMENDED_LENGTH,
        "summary": password_policy_summary(),
        "title": password_policy_title(),
        "hints": password_policy_hints(),
        "common_weak": list(PASSWORD_COMMON_WEAK),
    }


def username_policy_summary() -> str:
    return _registration_username_policy_summary()



def recovery_pin_policy_summary() -> str:
    return f"Recovery PIN must be {RECOVERY_PIN_MIN_LENGTH}-{RECOVERY_PIN_MAX_LENGTH} digits."


def validate_recovery_pin(pin: str | None) -> tuple[bool, str | None]:
    """Validate the low-entropy Recovery PIN used as a second reset secret.

    Echo-Chat intentionally keeps this rule narrow and consistent across setup,
    public registration, admin-created accounts, forgot-password, and reset flows.
    PINs are never stored plaintext; callers hash valid values before storage.
    """
    value = str(pin or "").strip()
    if not value:
        return False, "Recovery PIN is required."
    if not value.isdigit():
        return False, recovery_pin_policy_summary()
    if not (RECOVERY_PIN_MIN_LENGTH <= len(value) <= RECOVERY_PIN_MAX_LENGTH):
        return False, recovery_pin_policy_summary()
    return True, None


def _safe_recovery_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def recovery_pin_lock_settings(settings: dict | None) -> tuple[int, int]:
    """Return safe Recovery PIN lockout settings from hand-edited config.

    Hand-edited JSON/env-loaded settings should not make forgot/reset routes crash,
    disable lockout with zero attempts, or create absurd lock durations.
    """
    settings = settings or {}
    max_attempts = _safe_recovery_int(
        settings.get("recovery_pin_max_attempts"),
        RECOVERY_PIN_DEFAULT_MAX_ATTEMPTS,
        minimum=1,
        maximum=50,
    )
    lock_minutes = _safe_recovery_int(
        settings.get("recovery_pin_lock_minutes"),
        RECOVERY_PIN_DEFAULT_LOCK_MINUTES,
        minimum=1,
        maximum=1440,
    )
    return max_attempts, lock_minutes



def password_reset_limit_settings(settings: dict | None) -> tuple[int, int, int]:
    """Return safe password-reset token/rate settings from config.

    These values gate reset-link creation after username/email/PIN verification.
    They are clamped so hand-edited config cannot disable reset expiry, remove the
    per-account daily budget, or create an unbounded number of active links.
    """
    settings = settings or {}
    token_minutes = _safe_recovery_int(
        settings.get("password_reset_token_minutes"),
        PASSWORD_RESET_DEFAULT_TOKEN_MINUTES,
        minimum=1,
        maximum=1440,
    )
    daily_limit = _safe_recovery_int(
        settings.get("password_reset_daily_limit"),
        PASSWORD_RESET_DEFAULT_DAILY_LIMIT,
        minimum=1,
        maximum=25,
    )
    max_active_tokens = _safe_recovery_int(
        settings.get("password_reset_max_active_tokens"),
        PASSWORD_RESET_DEFAULT_MAX_ACTIVE_TOKENS,
        minimum=1,
        maximum=25,
    )
    return token_minutes, daily_limit, max_active_tokens

def password_policy_hints() -> list[str]:
    return [
        f"Use at least {PASSWORD_MIN_LENGTH} characters; {PASSWORD_RECOMMENDED_LENGTH}+ is better when practical.",
        "A passphrase with spaces is allowed.",
        "Do not use your username, email name, server name, or common passwords.",
        "Capital letters, numbers, and symbols are allowed, but not required. Length matters more.",
    ]


def _casefold(value: str | None) -> str:
    return str(value or "").casefold()


def _email_local_part(email: str | None) -> str:
    raw = str(email or "").strip().casefold()
    if "@" not in raw:
        return ""
    return raw.split("@", 1)[0]


def _compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _casefold(value))


def _deobfuscate_compact_password(value: str | None) -> str:
    return _compact(value).translate(_LEET_TRANSLATION)


def _is_repeated_chunk(compact: str, *, max_chunk: int = 8) -> bool:
    if len(compact) < PASSWORD_MIN_LENGTH:
        return False
    # Single/double character repetition is handled by this too, but keeping the
    # bounded chunk check catches qwertyqwertyqwerty and abc123abc123abc123.
    limit = min(max_chunk, max(1, len(compact) // 2))
    for size in range(1, limit + 1):
        if len(compact) % size:
            continue
        repeats = len(compact) // size
        if repeats < 3:
            continue
        chunk = compact[:size]
        if chunk and chunk * repeats == compact:
            return True
    return False


def _contains_obvious_sequence(compact: str) -> bool:
    if len(compact) < PASSWORD_MIN_LENGTH:
        return False
    # Require a long sequential run to avoid punishing normal words that contain
    # tiny alphabetic fragments. These are the classic keyboard/numeric runs.
    for sequence in _WEAK_SEQUENCE_SUBSTRINGS:
        for size in range(6, len(sequence) + 1):
            for start in range(0, len(sequence) - size + 1):
                if sequence[start:start + size] in compact:
                    return True
    return False


def _is_digit_padded_weak_seed(compact: str) -> bool:
    for seed in _WEAK_PASSWORD_SEEDS:
        if compact.startswith(seed):
            rest = compact[len(seed):]
            if rest and rest.isdigit():
                return True
        if compact.endswith(seed):
            rest = compact[:-len(seed)]
            if rest and rest.isdigit():
                return True
    return False


def _is_common_or_seeded_weak_password(password: str | None, compact: str) -> bool:
    folded = _casefold(password)
    variants = {compact, _deobfuscate_compact_password(password)}
    for variant in variants:
        if not variant:
            continue
        if variant in _COMMON_WEAK_PASSWORDS:
            return True
        if _is_digit_padded_weak_seed(variant):
            return True
        for seed in _WEAK_PASSWORD_SEEDS:
            if len(variant) >= PASSWORD_MIN_LENGTH and seed and variant == seed * (len(variant) // len(seed)):
                return True
        if _contains_obvious_sequence(variant):
            return True
    # Preserve the long-standing direct word check but keep this helper usable by
    # tests and by the meter shape. The caller returns the more specific message.
    return "passw0rd" in folded


def validate_account_password(
    password: str | None,
    *,
    username: str | None = None,
    email: str | None = None,
    server_name: str | None = None,
) -> tuple[bool, str | None]:
    """Validate a user-created password without old composition-rule traps.

    The policy intentionally does not require uppercase, lowercase, digits, or
    symbols. Current NIST/OWASP guidance favors length, allowing broad character
    sets, and rejecting obvious weak/context-derived passwords.
    """
    if password is None:
        return False, "Password is required."
    if password == "":
        return False, "Password is required."
    if _CONTROL_RE.search(password):
        return False, "Password cannot contain control characters."
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"Password too short (min {PASSWORD_MIN_LENGTH})."
    if len(password) > PASSWORD_MAX_LENGTH:
        return False, f"Password too long (max {PASSWORD_MAX_LENGTH})."

    folded = _casefold(password)
    compact = _compact(password)
    if "password" in folded or "passw0rd" in folded:
        return False, "Password cannot contain the word password."
    if _is_common_or_seeded_weak_password(password, compact):
        return False, "Password is too common. Use a longer passphrase."
    if len(set(compact)) <= 2 and len(compact) >= PASSWORD_MIN_LENGTH:
        return False, "Password is too repetitive. Use a longer passphrase."
    if _is_repeated_chunk(compact):
        return False, "Password is too repetitive. Use a longer passphrase."

    context_terms: Iterable[tuple[str, str]] = (
        ("username", _compact(username)),
        ("email name", _compact(_email_local_part(email))),
        ("server name", _compact(server_name)),
    )
    for label, term in context_terms:
        if len(term) >= 4 and term in compact:
            return False, f"Password cannot contain your {label}."

    return True, None


def validate_account_username_style(username: str | None) -> tuple[bool, str | None]:
    """Extra style checks layered on top of registration_name_policy."""
    raw = str(username or "")
    if _REPEATED_SEPARATORS_RE.search(raw):
        return False, "Username cannot contain repeated dot, underscore, or hyphen separators."
    return True, None
