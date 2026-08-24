from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "destructive_setting",
    (
        "CLOUDPAYMENTS_SANDBOX_DESTRUCTIVE_VERIFY",
        "CLOUDPAYMENTS_SANDBOX_TEST_MODE",
        "CLOUDPAYMENTS_SANDBOX_REFUND_TRANSACTION_ID",
        "CLOUDPAYMENTS_SANDBOX_RECURRING_TOKEN",
    ),
)
def test_sandbox_verify_fails_closed_for_legacy_destructive_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    destructive_setting: str,
) -> None:
    import scripts.cloudpayments_sandbox_verify as verify_module

    monkeypatch.setenv("CLOUDPAYMENTS_SANDBOX_VERIFY", "1")
    monkeypatch.setenv(destructive_setting, "1")
    monkeypatch.setattr(
        verify_module,
        "_build_adapter",
        lambda: pytest.fail("destructive configuration must be rejected before adapter creation"),
    )

    assert verify_module.main() == 2
    assert "destructive_sandbox_verification_not_supported" in capsys.readouterr().out
