"""
Secret redaction for text that is about to leave the machine (for example, sent to an LLM API).

SecretRedactor swaps likely secrets for stable placeholders like <REDACTED_SECRET_1>, and can
swap the original values back into text that comes back (for example, an LLM's rewritten code),
so the real values never have to be sent.

This is best-effort pattern matching, not a guarantee: it will miss secrets that do not look
like a password/token assignment or a well-known key format.
"""

import re
from typing import Dict, List

# name = "value" / name: "value" / "name": "value" where the name suggests a secret
_NAMED_SECRET = re.compile(
    r"""(?P<head>["']?[\w.\-]*(?:password|passwd|pwd|secret|api_?key|access_?key|private_?key|token|credential)[\w.\-]*["']?\s*[:=]\s*)"""
    r"""(?P<quote>["'])(?P<value>[^"'\n]{4,})(?P=quote)""",
    flags=re.IGNORECASE,
)

# Well-known key formats, matched anywhere in the text
_KEY_FORMATS: List["re.Pattern[str]"] = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),  # OpenAI-style
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key ids
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),  # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", flags=re.DOTALL),
]


class SecretRedactor:
    """Replaces secrets with placeholders. One instance keeps one mapping across several texts."""

    def __init__(self) -> None:
        self._placeholder_by_value: Dict[str, str] = {}
        self._value_by_placeholder: Dict[str, str] = {}

    @property
    def count(self) -> int:
        """Number of distinct secrets found so far."""
        return len(self._placeholder_by_value)

    def _placeholder_for(self, value: str) -> str:
        if value not in self._placeholder_by_value:
            placeholder = f"<REDACTED_SECRET_{len(self._placeholder_by_value) + 1}>"
            self._placeholder_by_value[value] = placeholder
            self._value_by_placeholder[placeholder] = value
        return self._placeholder_by_value[value]

    def redact(self, text: str) -> str:
        if not text:
            return text

        def named(m: "re.Match[str]") -> str:
            value = m.group("value")
            if value.startswith("<REDACTED_SECRET_"):
                return m.group(0)
            q = m.group("quote")
            return f"{m.group('head')}{q}{self._placeholder_for(value)}{q}"

        text = _NAMED_SECRET.sub(named, text)
        for pattern in _KEY_FORMATS:
            text = pattern.sub(lambda m: self._placeholder_for(m.group(0)), text)
        # Catch secrets already seen elsewhere, even where the surrounding syntax is different
        # (for example, inside JSON-escaped text)
        for value, placeholder in self._placeholder_by_value.items():
            text = text.replace(value, placeholder)
        return text

    def restore(self, text: str) -> str:
        """Put the original values back wherever a placeholder appears."""
        for placeholder, value in self._value_by_placeholder.items():
            text = text.replace(placeholder, value)
        return text
