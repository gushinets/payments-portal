from __future__ import annotations

from app.commands import expire_subscriptions as cli


def test_expiration_cli_runs_one_batch_with_configured_size(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

    def fake_expire(db, command):
        captured["db"] = db
        captured["command"] = command
        return [object(), object()]

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)

    assert cli.main(["--batch-size", "37"]) == 0

    assert captured["command"].batch_size == 37
    assert capsys.readouterr().out == "expired_subscriptions=2\n"
