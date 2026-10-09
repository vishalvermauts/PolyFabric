import pytest
from infinite_memory.security.secret_masker import SecretMasker, mask_secrets


def test_mask_openai_api_key():
    raw_code = 'openai_api_key = "sk-1234567890abcdef1234567890abcdef123456"'
    masked, redacted = mask_secrets(raw_code)
    assert "sk-1234567890abcdef" not in masked
    assert "<SECRET_REF:" in masked
    assert len(redacted) > 0


def test_mask_env_file_sensitive_keys():
    env_content = """
PORT=3000
DATABASE_URL=postgres://user:secretpassword123@localhost:5432/mydb
JWT_SECRET=supersecretjwttokenstring12345
PUBLIC_APP_NAME=MySaaS
"""
    masker = SecretMasker()
    masked = masker.mask(env_content)
    assert "secretpassword123" not in masked
    assert "supersecretjwttokenstring12345" not in masked
    assert "PORT=3000" in masked
    assert "PUBLIC_APP_NAME=MySaaS" in masked


def test_no_false_positives_on_clean_code():
    clean_code = """
def add(a: int, b: int) -> int:
    return a + b
"""
    masker = SecretMasker()
    assert not masker.contains_secrets(clean_code)
    assert masker.mask(clean_code) == clean_code
