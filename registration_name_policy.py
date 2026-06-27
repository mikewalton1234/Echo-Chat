from __future__ import annotations

import re
import unicodedata
from typing import Iterable

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 24
USERNAME_HTML_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{1,22}[A-Za-z0-9])"
USERNAME_ALLOWED_CHARS_LABEL = "letters, numbers, dot, underscore, or hyphen"


# Default registration bans cover impersonation-sensitive staff words plus
# explicit abuse terms the user asked to block. Admins can extend the list
# with the blocked_registration_terms setting.
_DEFAULT_BLOCKED_REGISTRATION_TERMS = (
    'admin',
    'administrator',
    'fuck',
    'fucker',
    'fuckerer',
    'phuck',
    'bitch',
    'cunt',
    'kkk',
    'lolita',
    'nigger',
    'nigga',
    'faggot',
    'rape',
    'rapist',
    'whore',
    'slut',
    'nazi',
    'nazis',
)

_CTRL_RE = re.compile(r"[\x00-\x1f]")
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_ALLOWED_USERNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,22}[a-z0-9])?$")
_REPEAT_RE = re.compile(r"(.)\1+")

# Basic leetspeak / obfuscation folding for comparison only.
_LEET_TRANS = str.maketrans({
    '@': 'a',
    '$': 's',
    '0': 'o',
    '1': 'i',
    '!': 'i',
    '3': 'e',
    '4': 'a',
    '5': 's',
    '7': 't',
})


def _settings_get(settings, key: str, default=None):
    if isinstance(settings, dict):
        return settings.get(key, default)
    return default


def normalize_registration_username(text: str) -> str:
    return unicodedata.normalize('NFKC', str(text or '')).strip().casefold()


def get_registration_username_min_length(settings=None) -> int:
    return USERNAME_MIN_LENGTH


def get_registration_username_max_length(settings=None) -> int:
    return USERNAME_MAX_LENGTH


def username_policy_summary(settings=None) -> str:
    mn = get_registration_username_min_length(settings)
    mx = get_registration_username_max_length(settings)
    return (
        f"Username must be {mn}-{mx} characters, use {USERNAME_ALLOWED_CHARS_LABEL}, "
        "start and end with a letter or number, and not repeat separators."
    )


def username_policy_title(settings=None) -> str:
    mn = get_registration_username_min_length(settings)
    mx = get_registration_username_max_length(settings)
    return (
        f"{mn}-{mx} characters. Letters, numbers, dot, underscore, and hyphen only. "
        "Must start and end with a letter or number. Do not repeat separators."
    )


def username_policy_metadata(settings=None) -> dict[str, object]:
    return {
        "min_length": get_registration_username_min_length(settings),
        "max_length": get_registration_username_max_length(settings),
        "html_pattern": USERNAME_HTML_PATTERN,
        "title": username_policy_title(settings),
        "summary": username_policy_summary(settings),
    }


def validate_registration_username_format(name: str, settings=None) -> tuple[bool, str | None]:
    username = normalize_registration_username(name)
    if not username:
        return False, 'Username missing'
    if _CTRL_RE.search(username):
        return False, 'Invalid username'

    mn = get_registration_username_min_length(settings)
    mx = get_registration_username_max_length(settings)
    if len(username) < mn:
        return False, f'Username too short (min {mn})'
    if len(username) > mx:
        return False, f'Username too long (max {mx})'
    if not _ALLOWED_USERNAME_RE.fullmatch(username):
        return False, f'Username may only use {USERNAME_ALLOWED_CHARS_LABEL}, and must start/end with a letter or number.'
    return True, None



def _fold_for_match(text: str) -> str:
    s = unicodedata.normalize('NFKC', str(text or '')).casefold()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return s.translate(_LEET_TRANS)



def _normalize_spaced(text: str) -> str:
    s = _fold_for_match(text)
    out = []
    prev_space = True
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        else:
            if not prev_space:
                out.append(' ')
            prev_space = True
    return _WS_RE.sub(' ', ''.join(out)).strip()



def _normalize_compact(text: str) -> str:
    return _NON_ALNUM_RE.sub('', _fold_for_match(text))



def _squash_repeated_chars(text: str) -> str:
    return _REPEAT_RE.sub(r'\1', text or '')



def _iter_extra_blocked_terms(settings=None) -> Iterable[str]:
    raw = _settings_get(settings, 'blocked_registration_terms', '')
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        text = str(raw).replace('\r', '\n').replace(';', '\n').replace(',', '\n')
        items = text.split('\n')
    cleaned = []
    seen = set()
    for item in items:
        s = str(item or '').strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned



def get_blocked_registration_terms(settings=None) -> list[str]:
    seen = set()
    terms = []
    for term in list(_DEFAULT_BLOCKED_REGISTRATION_TERMS) + list(_iter_extra_blocked_terms(settings)):
        s = str(term or '').strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(s)
    return terms



def find_blocked_registration_term(name: str, settings=None) -> str | None:
    if not bool(_settings_get(settings, 'block_registration_terms_enabled', True)):
        return None

    spaced = _normalize_spaced(name)
    compact = _normalize_compact(name)
    compact_squashed = _squash_repeated_chars(compact)
    if not compact:
        return None

    padded_spaced = f' {spaced} '
    for term in get_blocked_registration_terms(settings):
        term_spaced = _normalize_spaced(term)
        term_compact = _normalize_compact(term)
        term_compact_squashed = _squash_repeated_chars(term_compact)
        if not term_compact:
            continue

        if term_spaced and f' {term_spaced} ' in padded_spaced:
            return term

        if len(term_compact) >= 4 and (
            term_compact in compact
            or term_compact in compact_squashed
            or term_compact_squashed in compact_squashed
        ):
            return term

        if len(term_compact) <= 3 and compact == term_compact:
            return term

    return None



def validate_registration_username(name: str, settings=None) -> tuple[bool, str | None, str | None]:
    ok, err = validate_registration_username_format(name, settings=settings)
    if not ok:
        return False, err, None

    blocked = find_blocked_registration_term(name, settings=settings)
    if blocked:
        return False, 'That username is not allowed. Please choose a different username.', blocked

    return True, None, None
