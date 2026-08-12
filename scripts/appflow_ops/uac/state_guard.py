"""State payload privacy guard (defense-in-depth, not DLP).

Workspace isolation protects business boundaries. Payload guards reduce
accidental persistence of credentials, raw conversations, and other content
that does not belong in structured operational state (docs/account-state.md).

Rules:

- Forbidden keys are matched on a normalized key (lowercase, non-alphanumeric
  stripped) with exact/known-alias equality — never substring — so a business
  field like ``email_ctr`` is not falsely matched.
- Detection is recursive: nested dicts and lists inside facts/payloads are
  checked.
- String values are length-bounded (state is structured business state, not a
  document store); oversized free text is rejected with a predictable error.
- Email-shaped values are rejected as defense-in-depth.
- Fail closed: any violation raises :class:`StatePayloadError`; nothing is
  silently truncated or stripped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .types import ContractError

MAX_STRING_LENGTH = 2000
# Total canonical-JSON size of one payload (defense against dumping large
# structures); generous for real observations/decisions.
MAX_PAYLOAD_BYTES = 65536
# Maximum items in one list/tuple (a 1,000,000-row list must be rejected).
MAX_COLLECTION_ITEMS = 1000
# Maximum keys in one mapping (a 100,000-key dict must be rejected).
MAX_MAPPING_KEYS = 200
MAX_NESTING_DEPTH = 8

# Normalized (lowercase, non-alphanumeric stripped) exact keys that must
# never appear in structured state payloads.
_FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "accesstoken",
        "refreshtoken",
        "cookie",
        "cookies",
        "authorization",
        "secret",
        "apikey",
        "email",
        "clientemail",
        "customeremail",
        "rawchat",
        "conversation",
        "fullconversation",
        "screenshotblob",
        "imagebase64",
        "privatekey",
        "clientsecret",
    }
)

# Boundary search for obvious emails anywhere inside a string
# ("Contact user@example.com tomorrow" is rejected).
_EMAIL_VALUE_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Obvious credential/token material embedded in strings. Plain product URLs
# are NOT matched (state contract does not forbid URLs in general).
_TOKEN_STRING_RE = re.compile(
    r"(?:authorization\s*[:=]\s*bearer\s+[^\s]+|"
    r"access_token\s*=\s*[^\s&]+|\?token\s*=\s*[^\s&]+|api[_-]?key\s*[:=]\s*[^\s,;]+)",
    re.IGNORECASE,
)


class StatePayloadError(ContractError):
    """Raised when a payload violates the state privacy guard (fail closed)."""


def normalize_key(key: str) -> str:
    """Lowercase and strip non-alphanumeric characters for exact matching."""
    return "".join(character for character in key.lower() if character.isalnum())


def check_state_payload(payload: Mapping[str, Any], *, context: str) -> None:
    """Validate one state payload recursively; raise on violation.

    ``context`` names the payload for error messages (for example
    "observation facts", "decision payload").
    """

    _check_mapping(payload, context, _depth=0)
    size = len(canonical_json(payload).encode("utf-8", errors="replace"))
    if size > MAX_PAYLOAD_BYTES:
        raise StatePayloadError(
            f"{context}: payload exceeds {MAX_PAYLOAD_BYTES} bytes after "
            "canonical serialization; state is structured business state, "
            "not a document store"
        )


def _check_mapping(value: Mapping[str, Any], context: str, *, _depth: int) -> None:
    if _depth > MAX_NESTING_DEPTH:
        raise StatePayloadError(f"{context}: payload nesting too deep")
    if len(value) > MAX_MAPPING_KEYS:
        raise StatePayloadError(
            f"{context}: mapping has {len(value)} keys; limit is {MAX_MAPPING_KEYS}"
        )
    for key, item in value.items():
        if not isinstance(key, str):
            raise StatePayloadError(f"{context}: payload keys must be strings")
        if normalize_key(key) in _FORBIDDEN_KEYS:
            raise StatePayloadError(
                f"{context}: forbidden key {key!r} (credentials/raw chat/email "
                "do not belong in structured state)"
            )
        if isinstance(item, str):
            _check_string(item, key, context)
        elif isinstance(item, Mapping):
            _check_mapping(item, context, _depth=_depth + 1)
        elif isinstance(item, (list, tuple)):
            _check_sequence(item, context, _depth=_depth + 1)


def _check_sequence(value: Sequence[Any], context: str, *, _depth: int) -> None:
    if _depth > MAX_NESTING_DEPTH:
        raise StatePayloadError(f"{context}: payload nesting too deep")
    if len(value) > MAX_COLLECTION_ITEMS:
        raise StatePayloadError(
            f"{context}: collection has {len(value)} items; "
            f"limit is {MAX_COLLECTION_ITEMS}"
        )
    for item in value:
        if isinstance(item, str):
            _check_string(item, "<list item>", context)
        elif isinstance(item, Mapping):
            _check_mapping(item, context, _depth=_depth + 1)
        elif isinstance(item, (list, tuple)):
            _check_sequence(item, context, _depth=_depth + 1)


def _check_string(value: str, key: str, context: str) -> None:
    if len(value) > MAX_STRING_LENGTH:
        raise StatePayloadError(
            f"{context}: string field {key!r} exceeds {MAX_STRING_LENGTH} "
            "characters; state is structured business state, not a document store"
        )
    if _EMAIL_VALUE_RE.search(value):
        raise StatePayloadError(
            f"{context}: string field {key!r} contains an email address; "
            "identities do not belong in structured state"
        )
    if _TOKEN_STRING_RE.search(value):
        raise StatePayloadError(
            f"{context}: string field {key!r} contains credential/token "
            "material; secrets do not belong in structured state"
        )


def canonical_json(value: Any) -> str:
    """Deterministic JSON for digesting: stable key ordering, no spaces.

    Excludes nothing itself — callers must strip volatile fields
    (recorded_at, event_id, run_id) before calling.
    """

    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
