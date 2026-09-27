"""Filesystem ObjectStore for local development and multi-process tests (T04).

It honours the port semantics of the fake (bearer upload slots until expiry,
hash-verified promotion to immutable versions, revocation on delete) but
persists under one directory so the API and worker processes share it. Upload
URLs are HMAC-signed paths served by the API's local-only upload route. The
profile is FAKE mode, so composition refuses it outside local/test/preview.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from ...ports import storage as port
from ...ports.base import (
    CallContext,
    CapabilityProfile,
    Clock,
    Conflict,
    Environment,
    InvalidInput,
    NotFound,
    ProviderMode,
    Unauthenticated,
    check_mode_allowed,
    require_opaque_id,
)

UPLOAD_ROUTE = "/v1/dev/uploads/{upload_id}"


class LocalObjectStore:
    port_name = port.PORT

    def __init__(self, root: Path, *, signing_key: bytes, clock: Clock, environment: Environment,
                 public_base: str = "http://127.0.0.1:8000") -> None:
        check_mode_allowed(Environment.parse(environment), ProviderMode.FAKE)
        if len(signing_key) < 16:
            raise InvalidInput("signing_key_too_short")
        self.root = Path(root)
        (self.root / "uploads").mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        self._key = signing_key
        self._clock = clock
        self._base = public_base.rstrip("/")
        self.environment = Environment.parse(environment)
        self.profile = CapabilityProfile(port=port.PORT, provider="local-filesystem", mode=ProviderMode.FAKE,
                                         capabilities=frozenset({port.PRESIGNED_PUT, port.IMMUTABLE_VERSIONS,
                                                                 port.SERVER_SIDE_COPY, port.HARD_DELETE_VERSIONS,
                                                                 port.DOWNLOAD_TICKETS}))

    # --- helpers --------------------------------------------------------
    def _meta_path(self, upload_id: str) -> Path:
        return self.root / "uploads" / f"{require_opaque_id(upload_id, 'upload_id')}.json"

    def _read_meta(self, upload_id: str) -> dict:
        try:
            return json.loads(self._meta_path(upload_id).read_text())
        except (OSError, ValueError):
            raise NotFound("upload_not_found") from None

    def _write_json(self, path: Path, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)

    def _sign(self, upload_id: str, expires: str) -> str:
        return hmac.new(self._key, f"{upload_id}|{expires}".encode(), hashlib.sha256).hexdigest()

    def _check(self, ctx: CallContext) -> None:
        if ctx.environment is not self.environment:
            raise InvalidInput("environment_mismatch")
        ctx.check_deadline(self._clock)

    # --- simulated presigned PUT (served by the API in local/test) -------
    def accept_signed_put(self, upload_id: str, signature: str, data: bytes, content_type: str | None) -> None:
        meta = self._read_meta(upload_id)
        if meta.get("revoked"):
            raise NotFound("upload_not_found")
        if not hmac.compare_digest(self._sign(upload_id, meta["expires_at"]), signature or ""):
            raise Unauthenticated("bad_upload_signature")
        if self._clock.now() >= datetime.fromisoformat(meta["expires_at"]):
            raise Unauthenticated("upload_ticket_expired")
        if content_type is not None and content_type != meta["media_type"]:
            raise InvalidInput("content_type_mismatch")
        if len(data) > meta["max_bytes"]:
            raise InvalidInput("upload_too_large")
        (self.root / "uploads" / f"{upload_id}.bin").write_bytes(data)

    # --- port -------------------------------------------------------------
    def issue_upload_ticket(self, asset_id: str, media_type: str, policy: port.UploadPolicy,
                            ctx: CallContext) -> port.UploadTicket:
        self._check(ctx)
        require_opaque_id(asset_id, "asset_id")
        if media_type not in policy.allowed_media_types:
            raise InvalidInput("media_type_not_allowed")
        upload_id = f"upl_{os.urandom(12).hex()}"
        expires = self._clock.now() + timedelta(seconds=policy.expires_in_s)
        meta = {"asset_id": asset_id, "media_type": media_type, "max_bytes": policy.max_bytes,
                "expires_at": expires.isoformat(), "revoked": False, "promoted": None}
        self._write_json(self._meta_path(upload_id), meta)
        signature = self._sign(upload_id, meta["expires_at"])
        url = f"{self._base}{UPLOAD_ROUTE.format(upload_id=upload_id)}?sig={signature}"
        return port.UploadTicket(upload_id, asset_id, "PUT", url, expires, policy.max_bytes)

    def inspect_upload(self, upload_id: str, ctx: CallContext) -> port.UploadInspection:
        self._check(ctx)
        self._read_meta(upload_id)
        data_path = self.root / "uploads" / f"{upload_id}.bin"
        if not data_path.exists():
            return port.UploadInspection(upload_id, False, None, None, None)
        return port.UploadInspection(upload_id, True, data_path.stat().st_size, None, None)

    def promote_verified_input(self, upload_id: str, expected_sha256: str, ctx: CallContext) -> port.StoredObject:
        self._check(ctx)
        port.require_sha256(expected_sha256, "expected_sha256")
        meta = self._read_meta(upload_id)
        if meta.get("revoked"):
            raise NotFound("upload_missing")
        if meta.get("promoted"):
            promoted = port.StoredObject(**meta["promoted"])
            if promoted.sha256 == expected_sha256:
                return promoted
            raise Conflict("already_promoted_with_different_bytes")
        if self._clock.now() >= datetime.fromisoformat(meta["expires_at"]):
            raise Conflict("upload_expired")
        try:
            data = (self.root / "uploads" / f"{upload_id}.bin").read_bytes()
        except OSError:
            raise NotFound("upload_missing") from None
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise Conflict("digest_mismatch")
        if len(data) > meta["max_bytes"]:
            raise InvalidInput("upload_too_large")
        stored = self._put(meta["asset_id"], data, meta["media_type"])
        meta["promoted"] = stored.__dict__
        self._write_json(self._meta_path(upload_id), meta)
        return stored

    def _put(self, asset_id: str, data: bytes, media_type: str) -> port.StoredObject:
        folder = self.root / "objects" / asset_id
        folder.mkdir(exist_ok=True)
        digest = hashlib.sha256(data).hexdigest()
        version = f"v{digest[:24]}"
        target = folder / f"{version}.bin"
        if not target.exists():
            target.write_bytes(data)
            target.chmod(0o440)
        return port.StoredObject(asset_id, version, digest, len(data), media_type)

    def read_object(self, stored: port.StoredObject, ctx: CallContext) -> bytes:
        self._check(ctx)
        path = self.root / "objects" / require_opaque_id(stored.asset_id, "asset_id") / f"{stored.version_ref}.bin"
        if (self.root / "objects" / stored.asset_id / ".deleted").exists():
            raise NotFound("object_version_not_found")
        try:
            data = path.read_bytes()
        except OSError:
            raise NotFound("object_version_not_found") from None
        if hashlib.sha256(data).hexdigest() != stored.sha256:
            raise Conflict("stored_object_corrupted")
        return data

    def issue_download_ticket(self, stored: port.StoredObject, expires_in_s: int,
                              ctx: CallContext) -> port.DownloadTicket:
        self._check(ctx)
        self.read_object(stored, ctx)
        expires = self._clock.now() + timedelta(seconds=expires_in_s)
        return port.DownloadTicket(f"{self._base}/v1/dev/objects/{stored.asset_id}/{stored.version_ref}", expires)

    def write_derivative(self, asset_id: str, parent: port.StoredObject, data: bytes, media_type: str,
                         ctx: CallContext) -> port.StoredObject:
        self._check(ctx)
        require_opaque_id(asset_id, "asset_id")
        self.read_object(parent, ctx)
        if (self.root / "objects" / asset_id).exists():
            raise Conflict("asset_exists")
        return self._put(asset_id, bytes(data), media_type)

    def delete_asset_versions(self, asset_id: str, ctx: CallContext) -> port.DeletionReceipt:
        self._check(ctx)
        folder = self.root / "objects" / require_opaque_id(asset_id, "asset_id")
        count = 0
        if folder.exists():
            for file in folder.glob("*.bin"):
                file.chmod(0o640)
                file.unlink()
                count += 1
            (folder / ".deleted").touch()
        for meta_path in (self.root / "uploads").glob("*.json"):
            meta = json.loads(meta_path.read_text())
            if meta.get("asset_id") == asset_id and not meta.get("revoked"):
                meta["revoked"] = True
                self._write_json(meta_path, meta)
                (meta_path.with_suffix(".bin")).unlink(missing_ok=True)
        return port.DeletionReceipt(asset_id, count, complete=True)

    def verify_deletion(self, asset_id: str, ctx: CallContext) -> bool:
        self._check(ctx)
        folder = self.root / "objects" / require_opaque_id(asset_id, "asset_id")
        return not any(folder.glob("*.bin")) if folder.exists() else True
