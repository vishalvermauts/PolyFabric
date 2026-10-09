import re
from pathlib import Path
from typing import Tuple, Dict, Any, Set

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

# JSON/YAML/Dict key patterns: "password": "...", password: ..., 'token': '...'
JSON_YAML_SECRET_PATTERN = re.compile(
    r"""(?P<prefix>["']?(?P<key>[A-Za-z0-9_\-]+)["']?\s*[:=]\s*)(?P<quote>["'])(?P<val>[^"'\r\n]{4,})(?P=quote)""",
    re.MULTILINE
)

YAML_UNQUOTED_SECRET_PATTERN = re.compile(
    r"""^(?P<prefix>\s*(?P<key>[A-Za-z0-9_\-]+)\s*:\s*)(?P<val>[^\s#\r\n]{4,})(?P<suffix>\s*(?:#.*)?)$""",
    re.MULTILINE
)

SENSITIVE_KEY_NAMES = {
    "api_key", "apikey", "secret", "token", "password", "passwd", "pwd",
    "private_key", "auth_token", "access_token", "jwt", "database_url",
    "db_pass", "client_secret", "encryption_key", "master_key", "app_secret"
}

# Filenames and patterns that should never be indexed directly into vector DB
SENSITIVE_FILE_PATTERNS: Set[str] = {
    ".env", ".env.local", ".env.production", ".env.staging", ".env.test",
    "id_rsa", "id_ed25519", "credentials.json", "service-account.json",
    "secrets.yaml", "secrets.yml", "master.key"
}


def is_sensitive_file(file_path: str | Path) -> bool:
    """Check if a file should be excluded from indexing and writing due to credential risk."""
    name = Path(file_path).name.lower()
    if name in SENSITIVE_FILE_PATTERNS:
        return True
    if name.startswith(".env") and not name.endswith(".example") and not name.endswith(".template"):
        return True
    if name.endswith(".pem") or name.endswith(".key") or name.endswith(".p12") or name.endswith(".pfx"):
        return True
    return False


def mask_secrets(text: str) -> Tuple[str, Dict[str, str]]:
    """Mask secrets and API keys from code, JSON, YAML, and config text."""
    if not text:
        return "", {}

    redacted_map: Dict[str, str] = {}
    masked = text

    # 1. Mask structured env assignments
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

    # 2. Mask JSON/YAML/Dict sensitive keys
    def _replace_json_yaml(match):
        key_name = match.group("key")
        val = match.group("val")
        prefix = match.group("prefix")
        quote = match.group("quote")

        if any(s in key_name.lower() for s in SENSITIVE_KEY_NAMES) and len(val) >= 4:
            ref_token = f"<SECRET_REF:{key_name.upper()}>"
            redacted_map[ref_token] = key_name
            return f"{prefix}{quote}{ref_token}{quote}"
        return match.group(0)

    masked = JSON_YAML_SECRET_PATTERN.sub(_replace_json_yaml, masked)

    # 3. Mask unquoted YAML sensitive keys
    def _replace_yaml_unquoted(match):
        key_name = match.group("key")
        val = match.group("val")
        prefix = match.group("prefix")
        suffix = match.group("suffix")

        if any(s in key_name.lower() for s in SENSITIVE_KEY_NAMES) and len(val) >= 4:
            # Don't mask common booleans or numbers
            if val.lower() not in {"true", "false", "null", "none"}:
                ref_token = f"<SECRET_REF:{key_name.upper()}>"
                redacted_map[ref_token] = key_name
                return f"{prefix}{ref_token}{suffix}"
        return match.group(0)

    masked = YAML_UNQUOTED_SECRET_PATTERN.sub(_replace_yaml_unquoted, masked)

    # 4. Mask known high-entropy token patterns
    for pattern, label in SECRET_PATTERNS:
        matches = list(re.finditer(pattern, masked))
        for m in reversed(matches):
            token = f"<SECRET_REF:{label}>"
            redacted_map[token] = label
            start, end = m.span()
            masked = masked[:start] + token + masked[end:]

    return masked, redacted_map


class SecretMasker:
    """Zero-Trust Secret Shadowing for tool responses, indexing, and CLI transcripts."""

    def __init__(self):
        pass

    def mask(self, text: str) -> str:
        masked_text, _ = mask_secrets(text)
        return masked_text

    def contains_secrets(self, text: str) -> bool:
        _, redacted_map = mask_secrets(text)
        return len(redacted_map) > 0

    def is_sensitive_file(self, file_path: str | Path) -> bool:
        return is_sensitive_file(file_path)
