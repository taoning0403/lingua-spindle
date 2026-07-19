from __future__ import annotations

import subprocess

from linguaspindle.application import ApplicationService
from linguaspindle.config import Settings


class AvailablePort:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def connect_ex(self, _address) -> int:
        return 1


def test_doctor_probes_docker_engine_and_redacts_diagnostics(tmp_path, monkeypatch) -> None:
    runtime_value = "sk-" + "doctor-runtime-value"
    service = ApplicationService(Settings(data_dir=tmp_path / "data", openai_api_key=runtime_value))
    calls: list[list[str]] = []

    def docker_probe(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=f"api_key={runtime_value} cannot reach daemon",
        )

    monkeypatch.setattr("linguaspindle.application.shutil.which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr("linguaspindle.application.subprocess.run", docker_probe)
    monkeypatch.setattr("linguaspindle.application.socket.socket", lambda *_args: AvailablePort())
    monkeypatch.setattr("linguaspindle.application.platform.platform", lambda: "test-platform")
    try:
        report = service.doctor()
    finally:
        service.close()

    checks = {item["name"]: item for item in report["checks"]}
    assert calls == [["/usr/bin/docker", "version", "--format", "{{.Server.Version}}"]]
    assert checks["external_command:docker"]["ok"] is True
    assert checks["docker_engine"]["ok"] is False
    assert checks["docker_engine"]["optional"] is True
    assert runtime_value not in checks["docker_engine"]["detail"]
    assert "[REDACTED]" in checks["docker_engine"]["detail"]
    assert checks["external_assets:manga-image-translator-http"]["optional"] is True
    assert report["ok"] is True
