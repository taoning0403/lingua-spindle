from __future__ import annotations

from linguaspindle.security import redact, redact_text


def test_redacts_known_and_structural_secrets() -> None:
    secret = "sk-live-example"  # noqa: S105 - synthetic redaction fixture
    value = redact(
        {
            "api_key": secret,
            "message": f"Authorization: Bearer {secret}",
            "nested": [f"token={secret}"],
        },
        [secret],
    )
    assert secret not in str(value)
    assert value["api_key"] == "[REDACTED]"


def test_redacts_bearer_token() -> None:
    assert redact_text("Bearer abc.def") == "Bearer [REDACTED]"
