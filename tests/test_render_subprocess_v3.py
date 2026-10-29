"""R5-F2: versioned offline subprocess consumes only validated renderer input."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from princess_contracts import compile_document
from princess_app.adapters.render import SubprocessRenderer
from princess_app.ports.base import InvalidInput, PermanentFailure, TransientUnavailable


ROOT = Path(__file__).resolve().parents[1]
SOURCE_VIEW = json.loads((ROOT / "fixtures/reports/view.export-v2-no-image.json").read_text(encoding="utf-8"))


def envelope():
    # The legacy fixture's report language is sv-SE; the reviewed v3 renderer
    # language is a normalized presentation choice, not a different fact set.
    data = {
        "contract_version": "1.0.0",
        "renderer_version": "render-template/3",
        "view": SOURCE_VIEW,
        "premium": None,
        "evidence": None,
        "source_image": None,
        "layout": "A4",
        "detail": "SUMMARY",
        "locale": "sv",
        "generated_at": SOURCE_VIEW["generated_at"],
        "presentation_version": "presentation/1",
        "render_policy_version": "render-policy/3",
    }
    compiled = compile_document("RenderEnvelope", data)
    assert compiled.ok, compiled.issues
    return compiled.value


def test_v3_renderer_uses_separate_flag_bounded_credential_free_child(monkeypatch):
    import princess_app.adapters.render as module

    observed = []

    def fake_run(command, **kwargs):
        observed.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b"%PDF-1.7\nsynthetic")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setenv("PRINCESS_DATABASE_URL", "PRIVATE_TEST_PLACEHOLDER")
    monkeypatch.setenv("PRINCESS_STORAGE_READ_KEY", "PRIVATE_TEST_PLACEHOLDER")
    monkeypatch.setenv("PRINCESS_OPENAI_API_KEY", "PRIVATE_TEST_PLACEHOLDER")

    renderer = SubprocessRenderer(["node", "/tmp/mock-v3-render.mjs"], timeout_s=12.0)
    output = renderer.render_envelope_v3(envelope())
    assert output.startswith(b"%PDF-")
    assert len(observed) == 1
    command, kwargs = observed[0]
    assert command == ["node", "/tmp/mock-v3-render.mjs", "--envelope-v3"]
    assert kwargs["timeout"] == 12.0 and kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert set(kwargs["env"]) <= {"HOME", "PATH", "PRINCESS_CHROMIUM"}
    assert not set(kwargs["env"]) & {
        "PRINCESS_DATABASE_URL", "PRINCESS_STORAGE_READ_KEY", "PRINCESS_OPENAI_API_KEY",
    }
    assert len(kwargs["input"]) <= 8 * 1024 * 1024
    assert json.loads(kwargs["input"])["renderer_version"] == "render-template/3"
    assert json.loads(kwargs["input"])["premium"] is None


def test_v3_renderer_refuses_noncontract_input_before_subprocess(monkeypatch):
    import princess_app.adapters.render as module

    def do_not_spawn(*_args, **_kwargs):
        pytest.fail("unvalidated renderer payload reached child process")

    monkeypatch.setattr(module.subprocess, "run", do_not_spawn)
    for invalid in (None, {}, SOURCE_VIEW, "json"):
        with pytest.raises(InvalidInput, match="render_v3_envelope_required"):
            SubprocessRenderer().render_envelope_v3(invalid)


@pytest.mark.parametrize("code,returncode,exception", [
    (b"render_v3_source_not_authorized", 2, InvalidInput),
    (b"browser_output_failed", 1, PermanentFailure),
])
def test_v3_maps_only_redacted_child_error_codes(monkeypatch, code, returncode, exception):
    import princess_app.adapters.render as module

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=code)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    with pytest.raises(exception) as exc:
        SubprocessRenderer().render_envelope_v3(envelope())
    assert exc.value.code == code.decode("ascii")


def test_v3_enforces_legacy_stdout_and_timeout_ceiling(monkeypatch):
    import princess_app.adapters.render as module

    def huge(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stderr=b"", stdout=b"x" * (10 * 1024 * 1024 + 1))

    monkeypatch.setattr(module.subprocess, "run", huge)
    with pytest.raises(PermanentFailure, match="render_output_size"):
        SubprocessRenderer().render_envelope_v3(envelope())

    def timeout(*_args, **_kwargs):
        raise module.subprocess.TimeoutExpired(["node", "v3"], 5.0)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(TransientUnavailable, match="render_timeout"):
        SubprocessRenderer().render_envelope_v3(envelope())
