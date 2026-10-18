"""Git-source adversaries are built ONLY in disposable temporary repositories."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from tools import qualification_bootstrap as bootstrap
from evaluation.segmentation.run_qualification import _verify_staged_worktree


def _git(repo, *args, env=None, check=True):
    return subprocess.run(["git", *args], cwd=repo, env=env, check=check,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def _source(tmp_path, *, attributes=False):
    repo = tmp_path / "untrusted-source"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Synthetic Review")
    _git(repo, "config", "user.email", "review@example.invalid")
    (repo / "evaluation" / "segmentation").mkdir(parents=True)
    (repo / "evaluation" / "segmentation" / "run_qualification.py").write_text(
        "REVIEWED_SOURCE = True\n", encoding="utf-8"
    )
    (repo / "note.txt").write_bytes(b"approved raw blob\n")
    if attributes:
        (repo / ".gitattributes").write_text("note.txt filter=attack\n")
    _git(repo, "add", ".")
    _git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "reviewed A")
    return repo, _git(repo, "rev-parse", "HEAD")


def _stage(repo, sha, tmp_path):
    temp = tmp_path / "isolated"
    temp.mkdir()
    return bootstrap._stage_approved_source(repo, sha, temp)


def _poison(repo, marker, *, fsmonitor=False):
    script = repo.parent / ("fsmonitor-marker.sh" if fsmonitor else "smudge-marker.sh")
    if fsmonitor:
        script.write_text("#!/bin/sh\nprintf touched > " + str(marker) + "\nexit 0\n")
        script.chmod(0o755)
        _git(repo, "config", "core.fsmonitor", str(script))
    else:
        # Input bytes are passed through, so an ordinary checkout can look clean.
        script.write_text("#!/bin/sh\nprintf touched > " + str(marker) + "\ncat\n")
        script.chmod(0o755)
        _git(repo, "config", "filter.attack.smudge", str(script))
    return script


def test_approved_sha_ignores_replace_refs(tmp_path):
    repo, approved = _source(tmp_path)
    target = repo / "evaluation" / "segmentation" / "run_qualification.py"
    target.write_text("REVIEWED_SOURCE = False\n")
    _git(repo, "commit", "-qam", "unreviewed B")
    malicious = _git(repo, "rev-parse", "HEAD")
    assert approved != malicious
    _git(repo, "replace", approved, malicious)
    # The source Git object's replacement is real, not a no-op test fixture.
    assert _git(repo, "show", approved + ":evaluation/segmentation/run_qualification.py") == (
        "REVIEWED_SOURCE = False"
    )
    stage, env = _stage(repo, approved, tmp_path)
    assert (stage / "evaluation/segmentation/run_qualification.py").read_text() == (
        "REVIEWED_SOURCE = True\n"
    )
    assert _git(stage, "rev-parse", "HEAD", env=env) == approved
    assert not _git(stage, "status", "--porcelain", env=env)


def test_smudge_filter_cannot_execute_during_staging(tmp_path):
    repo, approved = _source(tmp_path, attributes=True)
    marker = tmp_path / "UNTRUSTED_SMUDGE_EXECUTED"
    _poison(repo, marker)
    stage, env = _stage(repo, approved, tmp_path)
    assert not marker.exists()
    assert (stage / "note.txt").read_bytes() == b"approved raw blob\n"
    assert not _git(stage, "status", "--porcelain", env=env)


def test_info_attributes_cannot_reintroduce_checkout_filter(tmp_path):
    repo, approved = _source(tmp_path)
    marker = tmp_path / "INFO_ATTRIBUTES_EXECUTED"
    _poison(repo, marker)
    info = repo / ".git" / "info" / "attributes"
    info.write_text("note.txt filter=attack\n")
    stage, _env = _stage(repo, approved, tmp_path)
    assert (stage / "note.txt").read_bytes() == b"approved raw blob\n"
    assert not marker.exists()


def test_fsmonitor_not_executed_by_bootstrap_or_worker_git_calls(tmp_path):
    repo, approved = _source(tmp_path)
    marker = tmp_path / "FSMONITOR_EXECUTED"
    _poison(repo, marker, fsmonitor=True)
    stage, env = _stage(repo, approved, tmp_path)
    assert not marker.exists()
    # Poison the *isolated* stage too: both status verification paths must
    # disable an unexpectedly configured fsmonitor, not just the bootstrap.
    _git(stage, "config", "core.fsmonitor", str(repo.parent / "fsmonitor-marker.sh"), env=env)
    _verify_staged_worktree(stage, approved)
    assert not marker.exists()


def test_environment_git_config_and_replacement_injection_stripped(tmp_path, monkeypatch):
    repo, approved = _source(tmp_path)
    marker = tmp_path / "ENVIRONMENT_GIT_EXECUTED"
    script = _poison(repo, marker, fsmonitor=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(script))
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
    monkeypatch.setenv("GIT_DIR", "/invalid/external/repository")
    monkeypatch.setenv("GIT_INDEX_FILE", "/invalid/index")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/invalid/objects")
    stage, env = _stage(repo, approved, tmp_path)
    assert not marker.exists()
    assert not _git(stage, "status", "--porcelain", env=env)
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert "GIT_CONFIG_COUNT" not in env


def test_source_repository_unchanged_by_snapshot(tmp_path):
    repo, approved = _source(tmp_path)
    (repo / "ignored-local-only.txt").write_text("untracked source data")
    before = (repo / ".git" / "config").read_bytes()
    worktrees_before = _git(repo, "worktree", "list", "--porcelain")
    stage, _env = _stage(repo, approved, tmp_path)
    assert stage.is_dir()
    assert (repo / ".git" / "config").read_bytes() == before
    assert _git(repo, "worktree", "list", "--porcelain") == worktrees_before
    assert (repo / "ignored-local-only.txt").read_text() == "untracked source data"


def test_packed_source_objects_are_accepted(tmp_path):
    repo, approved = _source(tmp_path)
    _git(repo, "gc", "--prune=now", "--quiet")
    assert list((repo / ".git" / "objects" / "pack").glob("*.pack"))
    stage, env = _stage(repo, approved, tmp_path)
    assert not _git(stage, "status", "--porcelain", env=env)


def test_missing_commit_fails_without_staging(tmp_path):
    repo, _ = _source(tmp_path)
    with pytest.raises(bootstrap._Rejected) as exc:
        _stage(repo, "a" * 40, tmp_path)
    assert exc.value.code == "Q_SOURCE"
    assert not (tmp_path / "isolated" / "checkout").exists()


def test_unreviewed_symlink_rejected(tmp_path):
    repo, _ = _source(tmp_path)
    (repo / "malicious-link").symlink_to("note.txt")
    _git(repo, "add", "malicious-link")
    _git(repo, "commit", "-qm", "unapproved symlink mode")
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(bootstrap._Rejected) as exc:
        _stage(repo, head, tmp_path)
    assert exc.value.code == "Q_SOURCE"
    assert not (tmp_path / "isolated" / "checkout").exists()


def test_executable_modes_and_exact_blob_bytes(tmp_path):
    repo, approved = _source(tmp_path)
    executable = repo / "command.sh"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    _git(repo, "add", "command.sh")
    _git(repo, "commit", "-qm", "reviewed executable")
    approved = _git(repo, "rev-parse", "HEAD")
    stage, env = _stage(repo, approved, tmp_path)
    assert (stage / "command.sh").read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert (stage / "command.sh").stat().st_mode & 0o777 == 0o755
    assert not _git(stage, "status", "--porcelain", env=env)


def test_unreviewed_source_bytecode_is_never_staged(tmp_path):
    repo, _ = _source(tmp_path)
    (repo / "evil.pyc").write_bytes(b"not reviewed code")
    _git(repo, "add", "evil.pyc")
    _git(repo, "commit", "-qm", "unreviewed bytecode")
    approved = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(bootstrap._Rejected) as exc:
        _stage(repo, approved, tmp_path)
    assert exc.value.code == "Q_SOURCE"


def test_policy_digest_checked_before_any_source_read(tmp_path, monkeypatch):
    repo, approved = _source(tmp_path)
    policy = tmp_path / "policy.json"
    policy.write_text("{}")
    digest = tmp_path / "approved.sha256"
    digest.write_text("0" * 64)
    manifests = []
    for kind in ("development", "validation", "holdout"):
        file = tmp_path / (kind + ".json")
        file.write_text("{}")
        manifests.append(file)
    data = tmp_path / "images"
    data.mkdir()
    args = argparse.Namespace(
        repository=repo, development=manifests[0], validation=manifests[1],
        holdout=manifests[2], policy=policy, approved_digest_file=digest,
        image_root=data, wheelhouse=None,
    )
    def forbidden(*_a, **_kw):
        pytest.fail("source objects read before independently approved policy")
    monkeypatch.setattr(bootstrap, "_stage_approved_source", forbidden)
    with pytest.raises(bootstrap._Rejected) as exc:
        bootstrap._run(args)
    assert exc.value.code == "Q_POLICY"
