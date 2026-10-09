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

# Universal line pattern supporting unified diff prefixes (+/-), export, quotes, whitespace, and colon/equals
UNIVERSAL_LINE_PATTERN = re.compile(
    r"""^(?P<diff_prefix>[+\-\t ]*)(?P<export>(?:export\s+)?)(?P<quote1>["']?)(?P<key>[A-Za-z0-9_\-]+)(?P=quote1)\s*(?P<delim>[:=])\s*(?P<quote2>["']?)(?P<val>[^\r\n#"'`]+?)(?P=quote2)(?P<suffix>\s*(?:#.*)?)$"""
)

# Inline dictionary / JSON object pattern: {"password": "...", "key": "..."}
INLINE_JSON_PATTERN = re.compile(
    r"""(?P<prefix>["']?(?P<key>[A-Za-z0-9_\-]+)["']?\s*[:=]\s*)(?P<quote>["'])(?P<val>[^"'\r\n]{4,})(?P=quote)"""
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
    """Mask secrets and API keys from code, diffs, JSON, YAML, and config text."""
    if not text:
        return "", {}

    redacted_map: Dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    masked_lines = []

    # 1. Line-by-line processing for assignments, diffs (+/-), and YAML
    for line in lines:
        # Strip newline for regex matching, preserve it for reconstruct
        ends_with_newline = line.endswith("\n")
        raw_line = line[:-1] if ends_with_newline else line
        if raw_line.endswith("\r"):
            raw_line = raw_line[:-1]
            nl = "\r\n"
        else:
            nl = "\n" if ends_with_newline else ""

        match = UNIVERSAL_LINE_PATTERN.match(raw_line)
        if match:
            key_name = match.group("key")
            val = match.group("val").strip()
            diff_prefix = match.group("diff_prefix")
            export_pfx = match.group("export")
            quote1 = match.group("quote1")
            delim = match.group("delim")
            quote2 = match.group("quote2")
            suffix = match.group("suffix")

            if any(s in key_name.lower() for s in SENSITIVE_KEY_NAMES) and len(val) >= 4:
                if val.lower() not in {"true", "false", "null", "none"}:
                    ref_token = f"<SECRET_REF:{key_name.upper()}>"
                    redacted_map[ref_token] = key_name
                    masked_line = f"{diff_prefix}{export_pfx}{quote1}{key_name}{quote1}{delim} {quote2}{ref_token}{quote2}{suffix}{nl}"
                    masked_lines.append(masked_line)
                    continue
        masked_lines.append(line)

    masked = "".join(masked_lines)

    # 2. Mask inline JSON / dictionary definitions
    def _replace_inline(match):
        key_name = match.group("key")
        val = match.group("val")
        prefix = match.group("prefix")
        quote = match.group("quote")

        if any(s in key_name.lower() for s in SENSITIVE_KEY_NAMES) and len(val) >= 4:
            ref_token = f"<SECRET_REF:{key_name.upper()}>"
            redacted_map[ref_token] = key_name
            return f"{prefix}{quote}{ref_token}{quote}"
        return match.group(0)

    masked = INLINE_JSON_PATTERN.sub(_replace_inline, masked)

    # 3. Mask known high-entropy token patterns
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
