"""
Aleph adapter to the lakehouse archive (ftm-lakehouse).

During the transition away from the servicelayer archive both backends are
available behind the shared archive protocol of
`openaleph_procrastinate.repository`. Which one holds the files of a collection
is decided by its `lakehouse_uri`: if it is set, they live in that (external)
lakehouse dataset, otherwise in the global servicelayer archive.

The shared protocol already covers retrieval (`load_file`, `local_path`,
`open`), so all that is added here is the per-collection storage uri and the
signed download urls the archive api hands out – the lakehouse doesn't
implement signing itself.
"""

from datetime import datetime
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from anystore.store.base import Store
from anystore.types import Uri
from ftm_lakehouse import get_archive as _get_archive
from ftm_lakehouse.core.conventions import path
from openaleph_procrastinate.repository import Archive as BaseArchive
from openaleph_procrastinate.repository import LakehouseArchive as BaseLakehouseArchive
from openaleph_procrastinate.repository import (
    ServicelayerArchive as BaseServicelayerArchive,
)
from servicelayer.archive.anystore import AnystoreArchive

if TYPE_CHECKING:
    from aleph.model.collection import Collection


class Archive(BaseArchive, Protocol):
    """The shared archive protocol plus the signed urls the api needs."""

    def generate_url(
        self,
        content_hash: str,
        file_name: str | None = None,
        mime_type: str | None = None,
        expire: datetime | None = None,
    ) -> str | None: ...


class ServicelayerArchive(BaseServicelayerArchive):
    """The legacy archive, which signs urls itself for the backends that can
    (s3, google cloud storage, anystore)."""

    def generate_url(
        self,
        content_hash: str,
        file_name: str | None = None,
        mime_type: str | None = None,
        expire: datetime | None = None,
    ) -> str | None:
        url: str | None = self._archive.generate_url(
            content_hash, file_name=file_name, mime_type=mime_type, expire=expire
        )
        return url


class LakehouseArchive(BaseLakehouseArchive):
    """The archive of a lakehouse dataset, addressed by its own storage uri
    instead of the global `LAKEHOUSE_URI` the shared implementation uses."""

    # Signing a blob url is the one thing neither the lakehouse nor the shared
    # protocol implement, and the servicelayer anystore archive already does it
    # for every backend `fsspec` can sign for – including the `anystore+http`
    # one a http lakehouse resolves to. Its implementation only reads `store`,
    # `_locate_key` and `TIMEOUT` off `self`, so it is borrowed here rather
    # than restated. It is deliberately not a base class: its constructor would
    # build a second store and, for a http lakehouse, insist on
    # `ARCHIVE_API_KEY` / `ARCHIVE_API_SECRET`.
    TIMEOUT = AnystoreArchive.TIMEOUT
    generate_url = AnystoreArchive.generate_url

    def __init__(self, dataset: str, uri: Uri) -> None:
        self._archive = _get_archive(dataset, uri=uri)
        self._is_local = self._archive._store.is_local
        self._base = "://".join(urlparse(str(uri))[:2])

    @property
    def store(self) -> Store:
        """The blob store, under the name the borrowed signing expects."""
        return self._archive._store

    def _locate_key(self, content_hash: str) -> str | None:
        """The key of an existing blob, or `None`. Overrides the servicelayer
        layout (`xx/yy/zz/<hash>`), which is not the one the lakehouse uses."""
        try:
            if self._archive.exists(content_hash):
                return path.archive_blob(content_hash)
        except ValueError:
            # the lakehouse only knows sha256 checksums, but a collection that
            # was moved there can still have sha1 hashes of the legacy archive
            # indexed
            pass
        return None

    def _sign_kwargs(self, *args, **kwargs) -> dict[str, Any]:
        sign_kwargs = AnystoreArchive._sign_kwargs(self, *args, **kwargs)
        sign_kwargs["base_url"] = self._base
        return sign_kwargs

    def archive_file(
        self, file_path: Path, mime_type: str | None = None, origin: str | None = None
    ) -> str:
        # A collection can only point at a lakehouse if it is external, so its
        # files are written by whatever manages that dataset, not by aleph.
        raise NotImplementedError("Lakehouse archive is read-only.")


@cache
def get_servicelayer_archive() -> Archive:
    """Get the global (legacy) archive. Stateless, so this is cached."""
    return ServicelayerArchive()


@lru_cache(1024)
def get_lakehouse_archive(dataset: str, uri: str) -> Archive:
    """Get the archive of a lakehouse dataset at the given storage uri."""
    return LakehouseArchive(dataset, uri)


def get_archive(collection: "Collection | None" = None) -> Archive:
    """Get the archive that holds the files of a collection: its own lakehouse
    dataset if it has a `lakehouse_uri`, the servicelayer archive otherwise."""
    if collection is not None and collection.lakehouse_uri:
        return get_lakehouse_archive(collection.foreign_id, collection.lakehouse_uri)
    return get_servicelayer_archive()
