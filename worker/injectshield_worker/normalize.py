"""Step 1 of the pipeline: undo the cheap obfuscation tricks before matching.

- Unicode NFKC (fullwidth and compatibility characters fold to ASCII)
- strip zero-width and bidi-control characters
- decode obvious base64 and URL-encoded blocks and append the decoded text,
  so the rules also see what was hidden

The obfuscation itself is a signal, so it is reported as a Finding too.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote

from injectshield_shared.models import Category

from .detectors.base import Finding, clip

DETECTOR = "normalize"

HIDDEN_CHARS = re.compile("[­᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]")
BASE64_BLOCK = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
URL_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")

HIDDEN_CHARS_WEIGHT = 0.25
ENCODED_PAYLOAD_WEIGHT = 0.3


@dataclass
class Normalized:
    text: str
    findings: list[Finding] = field(default_factory=list)


def normalize(text: str, category: Category = "prompt_injection") -> Normalized:
    findings: list[Finding] = []

    text = unicodedata.normalize("NFKC", text)

    hidden = HIDDEN_CHARS.findall(text)
    if hidden:
        text = HIDDEN_CHARS.sub("", text)
        findings.append(
            Finding(DETECTOR, "hidden_unicode", category, HIDDEN_CHARS_WEIGHT, f"{len(hidden)} hidden characters")
        )

    decoded_parts = []
    for match in BASE64_BLOCK.finditer(text):
        decoded = _decode_base64(match.group(0))
        if decoded:
            decoded_parts.append(decoded)
            findings.append(Finding(DETECTOR, "base64_payload", category, ENCODED_PAYLOAD_WEIGHT, clip(decoded)))

    if len(URL_ESCAPE.findall(text)) >= 3:
        decoded = unquote(text)
        if decoded != text:
            decoded_parts.append(decoded)
            findings.append(Finding(DETECTOR, "url_encoded_payload", category, ENCODED_PAYLOAD_WEIGHT, clip(decoded)))

    if decoded_parts:
        text = text + "\n" + "\n".join(decoded_parts)

    return Normalized(text=text, findings=findings)


def _decode_base64(block: str) -> str | None:
    """Return the decoded text if the block is base64 of readable text, else None."""
    padded = block + "=" * (-len(block) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
    # Hashes and keys decode to binary noise; hidden instructions decode to words.
    if printable / max(len(decoded), 1) < 0.95 or " " not in decoded:
        return None
    return decoded
