from __future__ import annotations

import re
import unicodedata
from typing import Iterable

_DEFAULT_MAX_ROOM_NAME_LENGTH = 48
_DEFAULT_MIN_ROOM_NAME_LENGTH = 3

# Seed defaults requested by the user, plus a small baseline of common hate/profanity terms.
# Admins can extend this list with the blocked_custom_room_terms setting.
_DEFAULT_BLOCKED_CUSTOM_ROOM_TERMS = (
    'kkk',
    'lolita',
    'nigger',
    'nigga',
    'faggot',
    'fuck',
    'cunt',
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
_RESERVED_AUTOSPLIT_SUFFIX_RE = re.compile(r"\(\s*\d+\s*\)\s*$")

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


def get_min_room_name_length(settings=None) -> int:
    try:
        mn = int(_settings_get(settings, 'min_room_name_length', _DEFAULT_MIN_ROOM_NAME_LENGTH) or _DEFAULT_MIN_ROOM_NAME_LENGTH)
    except Exception:
        mn = _DEFAULT_MIN_ROOM_NAME_LENGTH
    return max(1, min(mn, 32))


def get_max_room_name_length(settings=None) -> int:
    try:
        mx = int(_settings_get(settings, 'max_room_name_length', _DEFAULT_MAX_ROOM_NAME_LENGTH) or _DEFAULT_MAX_ROOM_NAME_LENGTH)
    except Exception:
        mx = _DEFAULT_MAX_ROOM_NAME_LENGTH
    return max(8, min(mx, 128))


def normalize_room_name(name: str) -> str:
    """Canonicalize user-entered room names for storage/display."""
    return _WS_RE.sub(' ', str(name or '').strip())


def validate_room_name_format(name: str, settings=None) -> tuple[bool, str | None]:
    room = normalize_room_name(name)
    if not room:
        return False, 'Room name missing'
    mn = get_min_room_name_length(settings)
    mx = get_max_room_name_length(settings)
    if len(room) < mn:
        return False, f'Room name too short (min {mn})'
    if len(room) > mx:
        return False, f'Room name too long (max {mx})'
    if _CTRL_RE.search(str(name or '')):
        return False, 'Invalid room name'
    m = _RESERVED_AUTOSPLIT_SUFFIX_RE.search(room)
    if m:
        try:
            shard_num = int(re.sub(r'\D+', '', m.group(0)) or 0)
        except Exception:
            shard_num = 0
        if shard_num >= 2:
            return False, 'Room names ending like overflow rooms, such as Room (2), are reserved'
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


def _iter_extra_blocked_terms(settings=None) -> Iterable[str]:
    raw = _settings_get(settings, 'blocked_custom_room_terms', '')
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


def get_blocked_custom_room_terms(settings=None) -> list[str]:
    seen = set()
    terms = []
    for term in list(_DEFAULT_BLOCKED_CUSTOM_ROOM_TERMS) + list(_iter_extra_blocked_terms(settings)):
        s = str(term or '').strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(s)
    return terms


def find_blocked_custom_room_term(name: str, settings=None) -> str | None:
    if not bool(_settings_get(settings, 'block_custom_room_terms_enabled', True)):
        return None

    spaced = _normalize_spaced(name)
    compact = _normalize_compact(name)
    if not compact:
        return None

    padded_spaced = f' {spaced} '
    for term in get_blocked_custom_room_terms(settings):
        term_spaced = _normalize_spaced(term)
        term_compact = _normalize_compact(term)
        if not term_compact:
            continue

        # Word / phrase match on normalized text.
        if term_spaced and f' {term_spaced} ' in padded_spaced:
            return term

        # Punctuation / spacing / simple leet obfuscation match, but avoid overblocking very short terms.
        if len(term_compact) >= 4 and term_compact in compact:
            return term

        # Special-case very short hard bans like "kkk" while still avoiding generic substring overblocking.
        if len(term_compact) <= 3 and compact == term_compact:
            return term

    return None


def validate_custom_room_creation_name(name: str, settings=None) -> tuple[bool, str | None, str | None]:
    name = normalize_room_name(name)
    ok, err = validate_room_name_format(name, settings=settings)
    if not ok:
        return False, err, None

    blocked = find_blocked_custom_room_term(name, settings=settings)
    if blocked:
        return False, 'That room name is not allowed. Please choose a different name.', blocked

    return True, None, None
