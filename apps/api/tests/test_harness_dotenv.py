"""Real dotenv files through the private startup pipeline; synthetic secrets only."""

from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.integrations.lbx.customer import sign_widget_jwt
from scripts import repo


@pytest.mark.parametrize(
    "wire,expected",
    [
        ("'synthetic-password\"'", 'synthetic-password"'),
        ('"synthetic-password\'"', "synthetic-password'"),
        (r'"synthetic-\"quote\"\\path"', 'synthetic-"quote"\\path'),
        (r"'synthetic-\'quote\'\\path'", "synthetic-'quote'\\path"),
        ("'  synthetic #$value  ' # comment", "  synthetic #$value  "),
        ('"synthetic #value" # comment', "synthetic #value"),
        ('synthetic-password"', 'synthetic-password"'),
        ("synthetic-password'", "synthetic-password'"),
        ("synthetic#value # comment", "synthetic#value"),
        ("'$literal-secret'", "$literal-secret"),
        ('""', ""),
        ("''", ""),
    ],
)
def test_dotenv_preserves_matching_quotes_escapes_and_literal_values(tmp_path: Path, wire: str, expected: str) -> None:
    path = tmp_path / ".env"
    path.write_text(f"# synthetic input\nSECRET={wire}\n", encoding="utf-8")
    assert repo.read_dotenv(path) == {"SECRET": expected}


@pytest.mark.parametrize("wire", ["'synthetic", '"synthetic', "'synthetic'junk", '"synthetic"junk'])
def test_dotenv_refuses_invalid_quoting_without_echoing_values(tmp_path: Path, wire: str) -> None:
    path = tmp_path / ".env"
    path.write_text(f"SECRET={wire}\n", encoding="utf-8")
    with pytest.raises(repo.HarnessError) as caught:
        repo.read_dotenv(path)
    assert "synthetic" not in str(caught.value)


@pytest.mark.parametrize("override", [False, True])
@pytest.mark.parametrize(
    "password_wire,signing_wire,password,signing",
    [
        ("'synthetic-password\"'", "'synthetic-signing\"'", 'synthetic-password"', 'synthetic-signing"'),
        ('"synthetic-password\'"', '"synthetic-signing\'"', "synthetic-password'", "synthetic-signing'"),
        (
            r'"synthetic-password\\path\"end"',
            r'"synthetic-signing\\path\"end"',
            'synthetic-password\\path"end',
            'synthetic-signing\\path"end',
        ),
        (r'"synthetic\tpassword"', r'"synthetic\tsigning"', "synthetic\tpassword", "synthetic\tsigning"),
    ],
)
def test_real_dotenv_preserves_lbx_credentials_through_settings_and_widget_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    override: bool,
    password_wire: str,
    signing_wire: str,
    password: str,
    signing: str,
) -> None:
    harness = tmp_path / ".harness"
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "HARNESS_DIR", harness)
    monkeypatch.setattr(repo, "RUNTIME_ENV", harness / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", harness / "runtime.json")
    reader = repo.read_dotenv
    monkeypatch.setattr(repo, "read_dotenv", lambda: reader(tmp_path / ".env"))
    for name in ("LBX_SERVER_PASSWORD", "LBX_WIDGET_SIGNING_SECRET", "LBX_BASE_URL", "LBX_SERVER_USERNAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "0")
    monkeypatch.setenv("KERNEL_BASE_URL", "")
    monkeypatch.setenv("KERNEL_SERVICE_TOKEN", "")
    (tmp_path / ".env").write_text(
        "LBX_BASE_URL=https://billing.test\nLBX_SERVER_USERNAME=synthetic-user\n"
        f"LBX_SERVER_PASSWORD={password_wire}\nLBX_WIDGET_SIGNING_SECRET={signing_wire}\n",
        encoding="utf-8",
    )
    if override:
        password, signing = "process-password'\" #$", "process-signing'\" #$"
        monkeypatch.setenv("LBX_SERVER_PASSWORD", password)
        monkeypatch.setenv("LBX_WIDGET_SIGNING_SECRET", signing)
    repo.write_runtime(repo.runtime_config(root=tmp_path))
    forwarded = repo.read_runtime_env()
    assert forwarded["LBX_SERVER_PASSWORD"] == password
    assert forwarded["LBX_WIDGET_SIGNING_SECRET"] == signing
    for name, value in forwarded.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.lbx_server_password.get_secret_value() == password
    assert settings.lbx_widget_signing_secret.get_secret_value() == signing
    credential = sign_widget_jwt(
        customer_id="345", secret=settings.lbx_widget_signing_secret, issued_at=1000
    ).get_secret_value()
    message, signature = credential.rsplit(".", 1)
    expected = (
        base64.urlsafe_b64encode(hmac.new(signing.encode(), message.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    assert hmac.compare_digest(signature, expected)
    assert repo.RUNTIME_ENV.stat().st_mode & 0o077 == 0
    for public in (repo.RUNTIME_JSON.read_text(), capsys.readouterr().out):
        assert password not in public and signing not in public and credential not in public


@pytest.mark.parametrize("escape", [r"\n", r"\r"])
def test_dotenv_decoded_line_breaks_cannot_enter_forwarded_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, escape: str
) -> None:
    harness = tmp_path / ".harness"
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "HARNESS_DIR", harness)
    monkeypatch.setattr(repo, "RUNTIME_ENV", harness / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", harness / "runtime.json")
    reader = repo.read_dotenv
    monkeypatch.setattr(repo, "read_dotenv", lambda: reader(tmp_path / ".env"))
    monkeypatch.delenv("LBX_SERVER_PASSWORD", raising=False)
    (tmp_path / ".env").write_text(f'LBX_SERVER_PASSWORD="synthetic{escape}password"\n', encoding="utf-8")
    with pytest.raises(repo.HarnessError, match="LBX_SERVER_PASSWORD must be a single-line value"):
        repo.write_runtime(repo.runtime_config(root=tmp_path))
    assert not repo.RUNTIME_ENV.exists()
