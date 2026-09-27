"""Fake private ObjectStore.

Simulates the races the completion algorithm must survive: a bearer upload
ticket stays writable until expiry (overwrite after inspection), partial
uploads, checksum mismatch, duplicate completion and delayed deletion.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ...ports import storage as port
from ...ports.base import CallContext, Conflict, InvalidInput, NotFound, Unauthenticated, require_opaque_id
from .base import FakeAdapter, SequentialIds


@dataclass
class _Upload:
    asset_id: str
    media_type: str
    policy: port.UploadPolicy
    expires_at: datetime
    data: bytes | None = None
    writes: int = 0
    promoted: port.StoredObject | None = None
    revoked: bool = False


@dataclass
class _Version:
    stored: port.StoredObject
    data: bytes
    deleted_at: datetime | None = None


@dataclass
class _Asset:
    versions: list[_Version] = field(default_factory=list)


class FakeObjectStore(FakeAdapter):
    port_name = port.PORT
    provider = "fake-object-store"
    default_capabilities = frozenset({port.PRESIGNED_PUT, port.IMMUTABLE_VERSIONS, port.SERVER_SIDE_COPY,
                                      port.DOWNLOAD_TICKETS, port.HARD_DELETE_VERSIONS})

    def __init__(self, *, delete_delay_s: float = 0.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ids = SequentialIds()
        self._uploads: dict[str, _Upload] = {}
        self._assets: dict[str, _Asset] = {}
        self.delete_delay_s = delete_delay_s

    # --- simulated client ----------------------------------------------
    def client_put(self, ticket: port.UploadTicket, data: bytes, *, media_type: str | None = None,
                   truncate_to: int | None = None) -> None:
        upload = self._uploads.get(ticket.upload_id)
        if upload is None or upload.revoked:
            raise NotFound("upload_not_found")
        if self.clock.now() >= upload.expires_at:
            raise Unauthenticated("upload_ticket_expired")
        if media_type is not None and media_type != upload.media_type:
            raise InvalidInput("content_type_mismatch")
        if self.profile.supports(port.ENFORCE_MAX_BYTES_AT_UPLOAD) and len(data) > upload.policy.max_bytes:
            raise InvalidInput("upload_too_large")
        upload.data = data if truncate_to is None else data[:truncate_to]
        upload.writes += 1

    # --- port -----------------------------------------------------------
    def issue_upload_ticket(self, asset_id: str, media_type: str, policy: port.UploadPolicy,
                            ctx: CallContext) -> port.UploadTicket:
        self.profile.require(port.PRESIGNED_PUT)
        require_opaque_id(asset_id, "asset_id")
        if media_type not in policy.allowed_media_types:
            raise InvalidInput("media_type_not_allowed")

        def effect() -> port.UploadTicket:
            upload_id = self._ids.new_id("upl")
            expires = self.clock.now() + timedelta(seconds=policy.expires_in_s)
            self._uploads[upload_id] = _Upload(asset_id, media_type, policy, expires)
            return port.UploadTicket(upload_id=upload_id, asset_id=asset_id, method="PUT",
                                     url=f"fake-store://upload/{upload_id}?sig=fake", expires_at=expires,
                                     max_bytes=policy.max_bytes)

        return self._run("issue_upload_ticket", ctx, effect)

    def inspect_upload(self, upload_id: str, ctx: CallContext) -> port.UploadInspection:
        def effect() -> port.UploadInspection:
            upload = self._uploads.get(upload_id)
            if upload is None:
                raise NotFound("upload_not_found")
            if upload.data is None:
                return port.UploadInspection(upload_id, False, None, None, None)
            digest = (hashlib.sha256(upload.data).hexdigest()
                      if self.profile.supports(port.PROVIDER_SHA256_CHECKSUM) else None)
            return port.UploadInspection(upload_id, True, len(upload.data), digest, f"w{upload.writes}")

        return self._run("inspect_upload", ctx, effect)

    def promote_verified_input(self, upload_id: str, expected_sha256: str, ctx: CallContext) -> port.StoredObject:
        self.profile.require(port.SERVER_SIDE_COPY)
        self.profile.require(port.IMMUTABLE_VERSIONS)
        port.require_sha256(expected_sha256, "expected_sha256")

        def effect() -> port.StoredObject:
            upload = self._uploads.get(upload_id)
            if upload is None or upload.revoked or upload.data is None:
                raise NotFound("upload_missing")
            if upload.promoted is not None:
                if upload.promoted.sha256 == expected_sha256:
                    return upload.promoted  # duplicate completion converges
                raise Conflict("already_promoted_with_different_bytes")
            if self.clock.now() >= upload.expires_at:
                raise Conflict("upload_expired")
            data = bytes(upload.data)  # copy exactly the bytes we hash
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                raise Conflict("digest_mismatch")
            if len(data) > upload.policy.max_bytes:
                raise InvalidInput("upload_too_large")
            stored = self._put_version(upload.asset_id, data, upload.media_type)
            upload.promoted = stored
            return stored

        return self._run("promote_verified_input", ctx, effect)

    def read_object(self, stored: port.StoredObject, ctx: CallContext) -> bytes:
        return self._run("read_object", ctx, lambda: self._live_version(stored).data)

    def issue_download_ticket(self, stored: port.StoredObject, expires_in_s: int,
                              ctx: CallContext) -> port.DownloadTicket:
        self.profile.require(port.DOWNLOAD_TICKETS)
        if type(expires_in_s) is not int or not 0 < expires_in_s <= 900:
            raise InvalidInput("invalid_ticket_lifetime")

        def effect() -> port.DownloadTicket:
            self._live_version(stored)
            return port.DownloadTicket(url=f"fake-store://get/{stored.version_ref}?sig=fake",
                                       expires_at=self.clock.now() + timedelta(seconds=expires_in_s))

        return self._run("issue_download_ticket", ctx, effect)

    def write_derivative(self, asset_id: str, parent: port.StoredObject, data: bytes, media_type: str,
                         ctx: CallContext) -> port.StoredObject:
        require_opaque_id(asset_id, "asset_id")

        def effect() -> port.StoredObject:
            self._live_version(parent)
            if asset_id in self._assets:
                raise Conflict("asset_exists")
            return self._put_version(asset_id, bytes(data), media_type)

        return self._run("write_derivative", ctx, effect)

    def delete_asset_versions(self, asset_id: str, ctx: CallContext) -> port.DeletionReceipt:
        self.profile.require(port.HARD_DELETE_VERSIONS)

        def effect() -> port.DeletionReceipt:
            asset = self._assets.get(asset_id)
            count = 0
            effective = self.clock.now() + timedelta(seconds=self.delete_delay_s)
            if asset is not None:
                for version in asset.versions:
                    if version.deleted_at is None:
                        version.deleted_at = effective
                        count += 1
            for upload in self._uploads.values():
                if upload.asset_id == asset_id:
                    upload.data = None
                    upload.revoked = True  # the bearer ticket can never recreate the asset
            return port.DeletionReceipt(asset_id, count, complete=self.delete_delay_s == 0)

        return self._run("delete_asset_versions", ctx, effect)

    def verify_deletion(self, asset_id: str, ctx: CallContext) -> bool:
        def effect() -> bool:
            asset = self._assets.get(asset_id)
            now = self.clock.now()
            open_slots = any(u.asset_id == asset_id and not u.revoked and now < u.expires_at
                             for u in self._uploads.values())
            gone = asset is None or all(v.deleted_at is not None and v.deleted_at <= now for v in asset.versions)
            return gone and not open_slots

        return self._run("verify_deletion", ctx, effect)

    # --- internals --------------------------------------------------------
    def _put_version(self, asset_id: str, data: bytes, media_type: str) -> port.StoredObject:
        asset = self._assets.setdefault(asset_id, _Asset())
        stored = port.StoredObject(asset_id=asset_id, version_ref=self._ids.new_id("ver"),
                                   sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                                   media_type=media_type)
        asset.versions.append(_Version(stored, data))
        return stored

    def _live_version(self, stored: port.StoredObject) -> _Version:
        asset = self._assets.get(stored.asset_id)
        for version in asset.versions if asset else ():
            if version.stored.version_ref == stored.version_ref:
                if version.deleted_at is not None and version.deleted_at <= self.clock.now():
                    break
                return version
        raise NotFound("object_version_not_found")
