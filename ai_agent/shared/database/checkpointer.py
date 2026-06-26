"""
基于 PostgreSQL 的 LangGraph CheckpointSaver 实现
替代 MemorySaver，支持服务重启后恢复图执行状态
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy import delete, desc, select

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from shared.database.connection import get_db
from shared.database.models import LangGraphCheckpoint, LangGraphWrite, LangGraphBlob

logger = logging.getLogger(__name__)


class PostgresCheckpointSaver(BaseCheckpointSaver[str]):
    """基于 PostgreSQL 的 CheckpointSaver

    参考 InMemorySaver 实现，将存储层替换为 PostgreSQL。
    使用 SQLAlchemy async 会话操作数据库。
    """

    def __init__(
        self,
        *,
        serde: SerializerProtocol | None = None,
    ) -> None:
        super().__init__(serde=serde)

    # ---------- async read ----------

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")

        async with get_db() as db:
            if checkpoint_id := get_checkpoint_id(config):
                # 按指定 checkpoint_id 查询
                result = await db.execute(
                    select(LangGraphCheckpoint).where(
                        LangGraphCheckpoint.thread_id == thread_id,
                        LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
                        LangGraphCheckpoint.checkpoint_id == checkpoint_id,
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    return await self._build_tuple(db, row, config)
            else:
                # 查询最新 checkpoint（按 checkpoint_id 降序，id 是 uuid6，单调递增）
                result = await db.execute(
                    select(LangGraphCheckpoint)
                    .where(
                        LangGraphCheckpoint.thread_id == thread_id,
                        LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
                    )
                    .order_by(desc(LangGraphCheckpoint.checkpoint_id))
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    return await self._build_tuple(
                        db, row,
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": row.checkpoint_id,
                            }
                        },
                    )
        return None

    async def _build_tuple(
        self, db, row: LangGraphCheckpoint, config: RunnableConfig
    ) -> CheckpointTuple:
        """从数据库行构建 CheckpointTuple"""
        thread_id = row.thread_id
        checkpoint_ns = row.checkpoint_ns
        checkpoint_id = row.checkpoint_id

        # 反序列化 checkpoint
        checkpoint_: Checkpoint = self.serde.loads_typed(
            (row.checkpoint_type, row.checkpoint_data)
        )

        # 加载 blobs（channel_values）
        channel_values = await self._load_blobs(db, thread_id, checkpoint_ns, checkpoint_["channel_versions"])

        # 反序列化 metadata
        metadata: CheckpointMetadata = self.serde.loads_typed(
            (row.metadata_type, row.metadata_data)
        )

        # 加载 writes
        writes_result = await db.execute(
            select(LangGraphWrite).where(
                LangGraphWrite.thread_id == thread_id,
                LangGraphWrite.checkpoint_ns == checkpoint_ns,
                LangGraphWrite.checkpoint_id == checkpoint_id,
            )
        )
        writes_rows = writes_result.scalars().all()
        pending_writes = [
            (w.task_id, w.channel, self.serde.loads_typed((w.value_type, w.value_data)))
            for w in writes_rows
        ]

        parent_config = (
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row.parent_checkpoint_id,
                }
            }
            if row.parent_checkpoint_id
            else None
        )

        return CheckpointTuple(
            config=config,
            checkpoint={**checkpoint_, "channel_values": channel_values},
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def _load_blobs(
        self, db, thread_id: str, checkpoint_ns: str, versions: ChannelVersions
    ) -> dict[str, Any]:
        channel_values: dict[str, Any] = {}
        for k, v in versions.items():
            result = await db.execute(
                select(LangGraphBlob).where(
                    LangGraphBlob.thread_id == thread_id,
                    LangGraphBlob.checkpoint_ns == checkpoint_ns,
                    LangGraphBlob.channel == k,
                    LangGraphBlob.version == str(v),
                )
            )
            blob = result.scalar_one_or_none()
            if blob and blob.type_name != "empty":
                channel_values[k] = self.serde.loads_typed((blob.type_name, blob.value_data))
        return channel_values

    # ---------- async list ----------

    def _build_list_conditions(
        self,
        thread_id: str | None,
        config_checkpoint_ns: str | None,
        config_checkpoint_id: str | None,
        before_checkpoint_id: str | None,
    ) -> list[Any]:
        """根据筛选参数构建 SQL WHERE 条件列表。"""
        conditions: list[Any] = []
        if thread_id:
            conditions.append(LangGraphCheckpoint.thread_id == thread_id)
        if config_checkpoint_ns is not None:
            conditions.append(LangGraphCheckpoint.checkpoint_ns == config_checkpoint_ns)
        if config_checkpoint_id:
            conditions.append(LangGraphCheckpoint.checkpoint_id == config_checkpoint_id)
        if before_checkpoint_id:
            conditions.append(LangGraphCheckpoint.checkpoint_id < before_checkpoint_id)
        return conditions

    def _passes_filter(self, row: LangGraphCheckpoint, filter: dict[str, Any] | None) -> bool:
        """检查行的 metadata 是否满足 filter 条件。"""
        if not filter:
            return True
        metadata = self.serde.loads_typed((row.metadata_type, row.metadata_data))
        return all(
            query_value == metadata.get(query_key)
            for query_key, query_value in filter.items()
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"] if config else None
        config_checkpoint_ns = config["configurable"].get("checkpoint_ns") if config else None
        config_checkpoint_id = get_checkpoint_id(config) if config else None
        before_checkpoint_id = get_checkpoint_id(before) if before else None

        async with get_db() as db:
            conditions = self._build_list_conditions(
                thread_id, config_checkpoint_ns, config_checkpoint_id, before_checkpoint_id
            )
            query = select(LangGraphCheckpoint).order_by(
                desc(LangGraphCheckpoint.checkpoint_id)
            )
            if conditions:
                query = query.where(*conditions)
            if limit is not None:
                query = query.limit(limit)

            result = await db.execute(query)
            rows = result.scalars().all()

            for row in rows:
                if not self._passes_filter(row, filter):
                    continue

                cfg = {
                    "configurable": {
                        "thread_id": row.thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.checkpoint_id,
                    }
                }
                yield await self._build_tuple(db, row, cfg)

    # ---------- async write ----------

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")

        # 拆分 channel_values 和 checkpoint
        c = checkpoint.copy()
        values: dict[str, Any] = c.pop("channel_values")  # type: ignore[misc]

        async with get_db() as db:
            # 1. 保存 blobs
            for k, v in new_versions.items():
                if k in values:
                    type_name, data = self.serde.dumps_typed(values[k])
                else:
                    type_name, data = "empty", b""
                await self._upsert_blob(db, thread_id, checkpoint_ns, k, str(v), type_name, data)

            # 2. 保存 checkpoint
            ckpt_type, ckpt_data = self.serde.dumps_typed(c)
            meta_type, meta_data = self.serde.dumps_typed(
                get_checkpoint_metadata(config, metadata)
            )
            parent_id = config["configurable"].get("checkpoint_id")

            # 删除同 thread/ns/id 的旧记录（理论上不会重复，但保险起见）
            await db.execute(
                delete(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == thread_id,
                    LangGraphCheckpoint.checkpoint_ns == checkpoint_ns,
                    LangGraphCheckpoint.checkpoint_id == checkpoint["id"],
                )
            )

            db.add(
                LangGraphCheckpoint(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint["id"],
                    checkpoint_type=ckpt_type,
                    checkpoint_data=ckpt_data,
                    metadata_type=meta_type,
                    metadata_data=meta_data,
                    parent_checkpoint_id=parent_id,
                )
            )
            await db.commit()

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def _upsert_blob(
        self, db, thread_id: str, checkpoint_ns: str, channel: str,
        version: str, type_name: str, data: bytes
    ):
        """插入或更新 blob"""
        await db.execute(
            delete(LangGraphBlob).where(
                LangGraphBlob.thread_id == thread_id,
                LangGraphBlob.checkpoint_ns == checkpoint_ns,
                LangGraphBlob.channel == channel,
                LangGraphBlob.version == version,
            )
        )
        db.add(
            LangGraphBlob(
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                channel=channel,
                version=version,
                type_name=type_name,
                value_data=data,
            )
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        async with get_db() as db:
            # 先查询已有的 writes，避免重复写入常规 write
            existing_result = await db.execute(
                select(LangGraphWrite.task_id, LangGraphWrite.write_idx).where(
                    LangGraphWrite.thread_id == thread_id,
                    LangGraphWrite.checkpoint_ns == checkpoint_ns,
                    LangGraphWrite.checkpoint_id == checkpoint_id,
                )
            )
            existing = set(existing_result.all())

            for idx, (c, v) in enumerate(writes):
                inner_idx = WRITES_IDX_MAP.get(c, idx)
                if inner_idx >= 0 and (task_id, inner_idx) in existing:
                    continue

                value_type, value_data = self.serde.dumps_typed(v)
                db.add(
                    LangGraphWrite(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        task_id=task_id,
                        write_idx=inner_idx,
                        channel=c,
                        value_type=value_type,
                        value_data=value_data,
                        task_path=task_path,
                    )
                )
            await db.commit()

    # ---------- async delete ----------

    async def adelete_thread(self, thread_id: str) -> None:
        async with get_db() as db:
            await db.execute(
                delete(LangGraphCheckpoint).where(
                    LangGraphCheckpoint.thread_id == thread_id
                )
            )
            await db.execute(
                delete(LangGraphWrite).where(
                    LangGraphWrite.thread_id == thread_id
                )
            )
            await db.execute(
                delete(LangGraphBlob).where(
                    LangGraphBlob.thread_id == thread_id
                )
            )
            await db.commit()

    # ---------- sync wrappers (run async in background thread) ----------

    def _run_async(self, coro):
        """在独立线程中运行异步协程，避免事件循环嵌套冲突。"""

        def _in_thread():
            return asyncio.run(coro)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(_in_thread).result()

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self._run_async(self.aget_tuple(config))

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        raise NotImplementedError("请使用异步接口 alist")

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self._run_async(self.aput(config, checkpoint, metadata, new_versions))

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._run_async(self.aput_writes(config, writes, task_id, task_path))

    def delete_thread(self, thread_id: str) -> None:
        self._run_async(self.adelete_thread(thread_id))
