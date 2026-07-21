from __future__ import annotations

from linguaspindle.security import collect_sensitive_values, redact, redact_text


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


def test_collects_nested_secret_values_without_recursing_or_rendering_keys() -> None:
    first_marker = "first-" + "private-value"
    second_marker = "second-" + "private-value"
    nested: dict[object, object] = {
        "api_key": first_marker,
        "items": [
            {"access_token": [second_marker, {"nested": first_marker}]},
            {object(): "ordinary"},
        ],
    }
    nested["cycle"] = nested

    assert collect_sensitive_values(nested) == (first_marker, second_marker)
    sanitized = redact(nested, (first_marker, second_marker))
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["cycle"] == "<recursive-reference>"
    assert first_marker not in str(sanitized)
    assert second_marker not in str(sanitized)
