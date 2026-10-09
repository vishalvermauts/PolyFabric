import re
from typing import Tuple, Dict, Any


# Regex patterns for common sensitive keys and tokens
SECRET_PATTERNS = [
    # OpenAI / Anthropic / general API keys
    (r"(sk-[a-zA-Z0-9_\-]{20,})", "API_KEY"),
    # AWS Access Key ID
    (r"(AKIA[0-9A-Z]{16})", "AWS_ACCESS_KEY"),
    # Generic bearer tokens
    (r"Bearer\s+([a-zA-Z0-9_\-\.]{20,})", "BEARER_TOKEN"),
    # JWT tokens
    (r"(eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]*)", "JWT_TOKEN"),
    # GitHub personal access tokens
    (r"(ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{50,})", "GITHUB_TOKEN"),
    # Slack tokens
    (r"(xox[baprs]-[a-zA-Z0-9\-]{10,})", "SLACK_TOKEN"),
    # Private RSA / SSH / EC keys
    (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----[A-Za-z0-9+/=\s\r\n]+-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "PRIVATE_KEY"),
]

# Config / .env line patterns: KEY_NAME = "secret_value"
ENV_ASSIGNMENT_PATTERN = re.compile(
    r"""^(?P<prefix>\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(?P<quote>["']?)(?P<val>[^"'\r\n]+)(?P=quote)(?P<suffix>.*)$""",
    re.MULTILINE
)

SENSITIVE_KEY_NAMES = {
    "api_key", "apikey", "secret", "token", "password", "passwd",
    "private_key", "auth_token", "access_token", "jwt", "database_url",
    "db_pass", "client_secret", "encryption_key"
}


def mask_secrets(text: str) -> Tuple[str, Dict[str, str]]:
    """Mask secrets and API keys from code/config text.
    
    Returns:
        (masked_text, redacted_map)
        where redacted_map maps ephemeral token -> label
    """
    if not text:
        return "", {}

    redacted_map: Dict[str, str] = {}
    masked = text

    # 1. Mask structured env assignments for sensitive keys
    def _replace_env(match):
        key_name = match.group("key")
        val = match.group("val").strip()
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        quote = match.group("quote")

        if any(s in key_name.lower() for s in SENSITIVE_KEY_NAMES) and len(val) >= 4:
            ref_token = f"<SECRET_REF:{key_name.upper()}>"
            redacted_map[ref_token] = key_name
            return f"{prefix}{quote}{ref_token}{quote}{suffix}"
        return match.group(0)

    masked = ENV_ASSIGNMENT_PATTERN.sub(_replace_env, masked)

    # 2. Mask known secret token regex patterns
    for pattern, label in SECRET_PATTERNS:
        matches = list(re.finditer(pattern, masked))
        for m in reversed(matches):
            raw_val = m.group(0)
            token = f"<SECRET_REF:{label}>"
            redacted_map[token] = label
            start, end = m.span()
            masked = masked[:start] + token + masked[end:]

    return masked, redacted_map


class SecretMasker:
    """Zero-Trust Secret Shadowing for tool responses and prompt transcripts."""

    def __init__(self):
        pass

    def mask(self, text: str) -> str:
        masked_text, _ = mask_secrets(text)
        return masked_text

    def contains_secrets(self, text: str) -> bool:
        _, redacted_map = mask_secrets(text)
        return len(redacted_map) > 0
