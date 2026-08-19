"""Armazenamento de blobs (MinIO) para documentos enviados ao RAG.

O cliente `minio` é síncrono; cada chamada roda em `asyncio.to_thread`, o
mesmo padrão já usado para leitura/parse bloqueante em `context/indexer.py`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from sicoobito.config import Settings
from sicoobito.logging_setup import get_logger

log = get_logger(__name__)


class BlobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket = settings.minio_documents_bucket
        # `region` fixo evita que o cliente tente descobrir a região com uma
        # chamada de rede (`GetBucketLocation`) antes de cada URL pré-assinada
        # — chamada que falharia para o `_public_client` abaixo, cujo endpoint
        # (a porta publicada no host) não é alcançável de dentro do container
        # da própria API.
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region="us-east-1",
        )
        # URLs pré-assinadas precisam do endpoint que o *browser* alcança, não
        # do endpoint interno (`minio:9000`) usado pelas chamadas server-to-server
        # — os dois só coincidem fora de container.
        public_endpoint = settings.effective_minio_public_endpoint
        self._public_client = (
            self._client
            if public_endpoint == settings.minio_endpoint
            else Minio(
                public_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                region="us-east-1",
            )
        )

    async def ensure_bucket(self) -> None:
        def _ensure() -> None:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)

        await asyncio.to_thread(_ensure)
        log.info("blob.bucket.ready", bucket=self.bucket)

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        def _put() -> None:
            self._client.put_object(
                self.bucket, key, BytesIO(data), length=len(data), content_type=content_type
            )

        await asyncio.to_thread(_put)

    async def get_object(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_get)

    async def object_exists(self, key: str) -> bool:
        """Usado para confirmar um upload feito direto pelo cliente via URL pré-assinada."""

        def _stat() -> bool:
            try:
                self._client.stat_object(self.bucket, key)
                return True
            except S3Error as exc:
                if exc.code in {"NoSuchKey", "NoSuchObject"}:
                    return False
                raise

        return await asyncio.to_thread(_stat)

    async def stat_size(self, key: str) -> int | None:
        """Tamanho real do objeto já enviado. O upload vai direto do cliente
        para o MinIO via URL pré-assinada — `size_bytes` declarado antes do
        upload não é garantia de nada, então quem confirma a ingestão precisa
        checar o tamanho de verdade contra o objeto já gravado."""

        def _stat() -> int | None:
            try:
                info = self._client.stat_object(self.bucket, key)
                return info.size
            except S3Error as exc:
                if exc.code in {"NoSuchKey", "NoSuchObject"}:
                    return None
                raise

        return await asyncio.to_thread(_stat)

    async def remove_object(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self.bucket, key)

    async def list_object_keys(self, prefix: str) -> list[tuple[str, datetime | None]]:
        """Chave + data de modificação de cada objeto sob `prefix` — usado só
        pela rotina de limpeza de replays órfãos (`browser/replay.py`), nunca
        pelo caminho normal de upload/leitura de documentos."""

        def _list() -> list[tuple[str, datetime | None]]:
            return [
                (obj.object_name, obj.last_modified)
                for obj in self._client.list_objects(self.bucket, prefix=prefix, recursive=True)
            ]

        return await asyncio.to_thread(_list)

    async def presigned_put_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        return await asyncio.to_thread(
            self._public_client.presigned_put_object,
            self.bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )

    async def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        return await asyncio.to_thread(
            self._public_client.presigned_get_object,
            self.bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )
