from __future__ import annotations

import asyncio
import hashlib
import threading
from types import SimpleNamespace

import anyio
import pytest

import ai_agent.agent_guard.runtime as runtime_module
from ai_agent.agent_guard.config import AgentGuardConfig
from ai_agent.agent_guard.consumer import AgentSessionEventHandler
from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository, RollbackDeletionBlocked
from ai_agent.agent_guard.runtime import AgentGuardRuntime, JsonKafkaConsumerTask


class ConsumerStub:
    def __init__(self, messages):
        self.messages = list(messages)
        self.commits = 0
        self.yielded = []

    def __aiter__(self):
        async def iterate():
            for message in self.messages:
                self.yielded.append(message)
                yield message

        return iterate()

    async def commit(self):
        self.commits += 1


class PositionedConsumerStub(ConsumerStub):
    def __init__(self, messages):
        super().__init__(messages)
        self.position = 0
        self.yielded = []

    def __aiter__(self):
        async def iterate():
            while self.position < len(self.messages):
                message = self.messages[self.position]
                self.position += 1
                self.yielded.append(message)
                yield message

        return iterate()


class ProducerStub:
    async def start(self):
        return None

    async def stop(self):
        return None


class DbContextStub:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


def test_json_consumer_commits_only_after_handler_success():
    async def run_test():
        order = []
        task = JsonKafkaConsumerTask("kafka:9092", "topic", "group", handler=None)
        consumer = ConsumerStub(
            [
                SimpleNamespace(value=b'{"run_id":"run-1"}'),
                SimpleNamespace(value=b'{"run_id":"run-2"}'),
            ]
        )

        async def handler(_payload, _cancellation_token):
            order.extend(["handler-start", "handler-end"])
            task.running = False

        async def commit():
            order.append("commit")
            await ConsumerStub.commit(consumer)

        task.handler = handler
        task.consumer = consumer
        consumer.commit = commit
        task.running = True
        await task._run()

        assert order == ["handler-start", "handler-end", "commit"]
        assert consumer.commits == 1
        assert len(consumer.yielded) == 1

    anyio.run(run_test)


def test_json_consumer_does_not_commit_after_handler_failure(monkeypatch):
    async def run_test():
        order = []
        task = JsonKafkaConsumerTask("kafka:9092", "topic", "group", handler=None)
        consumer = ConsumerStub([SimpleNamespace(value=b'{"run_id":"run-1"}')])

        async def handler(_payload, _cancellation_token):
            order.append("handler")
            raise RuntimeError("handler failed")

        async def stop_after_failure(_delay):
            task.running = False

        task.handler = handler
        task.consumer = consumer
        monkeypatch.setattr(asyncio, "sleep", stop_after_failure)
        task.running = True
        await task._run()

        assert order == ["handler"]
        assert consumer.commits == 0

    anyio.run(run_test)


def test_session_consumer_retries_failed_message_before_advancing(monkeypatch):
    async def run_test():
        seen = []
        retry_delays = []
        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=None,
            max_handler_attempts=2,
            retry_backoff_seconds=7,
        )
        consumer = PositionedConsumerStub(
            [
                SimpleNamespace(value=b'{"run_id":"failed"}'),
                SimpleNamespace(value=b'{"run_id":"succeeds-after"}'),
            ]
        )

        async def handler(payload, _cancellation_token):
            run_id = payload["run_id"]
            seen.append(run_id)
            if run_id == "failed" and seen.count("failed") == 1:
                raise RuntimeError("retry this message")
            if run_id == "succeeds-after":
                task.running = False

        async def retry_without_delay(delay):
            retry_delays.append(delay)
            return None

        task.handler = handler
        task.consumer = consumer
        monkeypatch.setattr(asyncio, "sleep", retry_without_delay)
        task.running = True
        await task._run()

        assert (seen, consumer.commits) == (
            ["failed", "failed", "succeeds-after"],
            2,
        )
        assert len(consumer.yielded) == 2
        assert retry_delays == [7]

    anyio.run(run_test)


def test_session_consumer_stops_fail_closed_after_retry_exhaustion(monkeypatch, caplog):
    async def run_test():
        seen = []
        retry_delays = []
        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "agent.session.finished",
            "session-group",
            handler=None,
            max_handler_attempts=3,
            retry_backoff_seconds=5,
        )
        consumer = PositionedConsumerStub(
            [
                SimpleNamespace(value=b'{"run_id":"poison"}'),
                SimpleNamespace(value=b'{"run_id":"must-not-run"}'),
            ]
        )
        real_sleep = asyncio.sleep

        async def handler(payload, _cancellation_token):
            seen.append(payload["run_id"])
            raise ValueError("deterministic failure")

        async def retry_without_delay(delay):
            retry_delays.append(delay)
            await real_sleep(0)

        task.handler = handler
        task.consumer = consumer
        monkeypatch.setattr(asyncio, "sleep", retry_without_delay)
        task.running = True

        await asyncio.wait_for(task._run(), timeout=0.2)

        assert seen == ["poison", "poison", "poison"]
        assert retry_delays == [5, 5]
        assert consumer.commits == 0
        assert [message.value for message in consumer.yielded] == [b'{"run_id":"poison"}']
        assert task.running is False
        assert any(record.levelname == "CRITICAL" for record in caplog.records)

    anyio.run(run_test)


class LifecycleConsumerStub:
    def __init__(self):
        self.started = asyncio.Event()
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self):
        self.start_calls += 1

    async def stop(self):
        self.stop_calls += 1

    def __aiter__(self):
        async def iterate():
            self.started.set()
            await asyncio.Event().wait()
            if False:
                yield None

        return iterate()


class ActiveLifecycleConsumerStub(ConsumerStub):
    def __init__(self, messages):
        super().__init__(messages)
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self):
        self.start_calls += 1

    async def stop(self):
        self.stop_calls += 1


def test_json_consumer_passes_explicit_max_poll_interval_to_aiokafka(monkeypatch):
    async def run_test():
        captured = {}
        consumer = LifecycleConsumerStub()

        def consumer_factory(*_args, **kwargs):
            captured.update(kwargs)
            return consumer

        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", consumer_factory)
        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=None,
            max_poll_interval_ms=1_800_000,
        )

        await task.start()
        try:
            assert captured["max_poll_interval_ms"] == 1_800_000
        finally:
            await task.stop()

    anyio.run(run_test)


def test_runtime_propagates_poll_and_llm_timeouts_from_config(monkeypatch):
    async def run_test():
        llm = SimpleNamespace(request_timeout_seconds=None)
        config = AgentGuardConfig(
            kafka_max_poll_interval_ms=1_800_000,
            session_handler_timeout_seconds=300,
            llm_request_timeout_seconds=75,
            session_handler_max_attempts=4,
            session_retry_backoff_seconds=6,
            consumer_drain_timeout_seconds=45,
        )
        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=config,
            llm=llm,
        )

        monkeypatch.setattr(runtime_module, "AIOKafkaProducer", lambda **_kwargs: ProducerStub())

        async def skip_consumer_start(_consumer_task):
            return None

        monkeypatch.setattr(JsonKafkaConsumerTask, "start", skip_consumer_start)

        await runtime.start()

        assert [consumer.max_poll_interval_ms for consumer in runtime.consumers] == [
            1_800_000,
            1_800_000,
        ]
        assert llm.request_timeout_seconds == 75
        session_consumer, rollback_consumer = runtime.consumers
        assert session_consumer.max_handler_attempts == 4
        assert session_consumer.handler_timeout_seconds == 300
        assert session_consumer.retry_backoff_seconds == 6
        assert rollback_consumer.max_handler_attempts == 1
        assert [consumer.drain_timeout_seconds for consumer in runtime.consumers] == [45, 45]

    anyio.run(run_test)


def test_rollback_consumer_does_not_repeat_side_effects_after_partial_success(monkeypatch, caplog):
    async def run_test():
        side_effects = []
        request_ids = []
        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=AgentGuardConfig(
                session_handler_max_attempts=3,
                session_retry_backoff_seconds=1,
            ),
            llm=SimpleNamespace(request_timeout_seconds=None),
        )
        monkeypatch.setattr(runtime_module, "AIOKafkaProducer", lambda **_kwargs: ProducerStub())

        async def skip_consumer_start(_consumer_task):
            return None

        async def execute_with_restore_and_publish(request, **_kwargs):
            request_ids.append(request["id"])
            side_effects.extend(["restore", "publish"])
            return {
                **request,
                "event_type": "agent.rollback.completed",
                "status": "completed",
                "error": None,
                "command_results": [],
            }

        class RepositoryStub:
            async def claim_rollback_execution(self, rollback):
                side_effects.append(("claim", rollback["id"]))
                return "claimed"

            async def finish_rollback_execution(self, rollback):
                side_effects.append(("finish_rollback", rollback["id"]))
                raise RuntimeError("database unavailable after publish")

            async def update_session(self, _run_id, _updates):
                side_effects.append("update_session")

        monkeypatch.setattr(JsonKafkaConsumerTask, "start", skip_consumer_start)
        monkeypatch.setattr(runtime_module, "execute_rollback_request", execute_with_restore_and_publish)
        monkeypatch.setattr(runtime_module, "get_db", DbContextStub)
        monkeypatch.setattr(runtime_module, "SqlAlchemyAgentSessionRepository", lambda _db: RepositoryStub())
        await runtime.start()

        rollback_consumer = runtime.consumers[1]
        rollback_consumer.consumer = PositionedConsumerStub(
            [
                SimpleNamespace(
                    value=b'{"id":"rollback-stable","run_id":"run-1","nono_session_id":"nono-1"}'
                ),
                SimpleNamespace(
                    value=b'{"id":"rollback-next","run_id":"run-2","nono_session_id":"nono-2"}'
                ),
            ]
        )
        rollback_consumer.running = True

        await rollback_consumer._run()

        assert request_ids == ["rollback-stable"]
        assert side_effects == [
            ("claim", "rollback-stable"),
            "restore",
            "publish",
            ("finish_rollback", "rollback-stable"),
        ]
        assert rollback_consumer.consumer.commits == 0
        assert len(rollback_consumer.consumer.yielded) == 1
        assert rollback_consumer.running is False
        assert any(record.levelname == "CRITICAL" for record in caplog.records)

    anyio.run(run_test)


def test_rollback_redelivery_after_crash_does_not_repeat_commands(monkeypatch):
    async def run_test():
        repository = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-crash",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repository.store_rollback(request)
        command_calls = []

        async def execute_then_crash(event, **_kwargs):
            command_calls.append((event["id"], event["nono_session_id"], event.get("snapshot", 0)))
            raise RuntimeError("process crashed after restore")

        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=AgentGuardConfig(),
            llm=SimpleNamespace(request_timeout_seconds=None),
        )
        monkeypatch.setattr(runtime_module, "get_db", DbContextStub)
        monkeypatch.setattr(runtime_module, "SqlAlchemyAgentSessionRepository", lambda _db: repository)
        monkeypatch.setattr(runtime_module, "execute_rollback_request", execute_then_crash)
        publisher = SimpleNamespace()

        with pytest.raises(RuntimeError, match="process crashed"):
            await runtime._handle_rollback_requested(request, publisher)

        assert (await repository.get_rollback("rollback-crash"))["status"] == "executing"

        with pytest.raises(RuntimeError, match="already executing"):
            await runtime._handle_rollback_requested(request, publisher)

        assert command_calls == [("rollback-crash", "nono-1", 0)]

    anyio.run(run_test)


def test_published_rollback_message_survives_delete_attempt_and_claims(monkeypatch):
    async def run_test():
        repository = InMemoryAgentSessionRepository()
        await repository.upsert_session(
            {
                "run_id": "run-1",
                "nono": {"session_id": "nono-1"},
                "original_request": "modify README",
                "rollback_status": "requested",
            }
        )
        request = {
            "id": "rollback-published",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repository.store_rollback(request)
        with pytest.raises(RollbackDeletionBlocked):
            await repository.delete_session("run-1")

        executed = []

        async def execute_once(event, **_kwargs):
            executed.append(event["id"])
            return {
                **event,
                "event_type": "agent.rollback.completed",
                "status": "completed",
                "error": None,
                "command_results": [{"exit_code": 0}],
            }

        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=AgentGuardConfig(),
            llm=SimpleNamespace(request_timeout_seconds=None),
        )
        monkeypatch.setattr(runtime_module, "get_db", DbContextStub)
        monkeypatch.setattr(runtime_module, "SqlAlchemyAgentSessionRepository", lambda _db: repository)
        monkeypatch.setattr(runtime_module, "execute_rollback_request", execute_once)

        await runtime._handle_rollback_requested(request, SimpleNamespace())

        assert executed == ["rollback-published"]
        assert (await repository.get_rollback("rollback-published"))["status"] == "completed"

    anyio.run(run_test)


def test_rollback_terminal_redelivery_skips_commands(monkeypatch):
    async def run_test():
        repository = InMemoryAgentSessionRepository()
        request = {
            "id": "rollback-complete",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "completed",
        }
        await repository.store_rollback(request)

        async def must_not_execute(*_args, **_kwargs):
            raise AssertionError("terminal rollback redelivery executed commands")

        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=AgentGuardConfig(),
            llm=SimpleNamespace(request_timeout_seconds=None),
        )
        monkeypatch.setattr(runtime_module, "get_db", DbContextStub)
        monkeypatch.setattr(runtime_module, "SqlAlchemyAgentSessionRepository", lambda _db: repository)
        monkeypatch.setattr(runtime_module, "execute_rollback_request", must_not_execute)

        await runtime._handle_rollback_requested(request, SimpleNamespace())

        assert (await repository.get_rollback("rollback-complete"))["status"] == "completed"

    anyio.run(run_test)


@pytest.mark.parametrize("terminal_status", ["completed", "failed"])
def test_rollback_execution_records_terminal_ledger_status(monkeypatch, terminal_status):
    async def run_test():
        repository = InMemoryAgentSessionRepository()
        request = {
            "id": f"rollback-{terminal_status}",
            "run_id": "run-1",
            "nono_session_id": "nono-1",
            "snapshot": 0,
            "requested_by": "user-1",
            "status": "requested",
        }
        await repository.store_rollback(request)

        async def execute(event, **_kwargs):
            return {
                **event,
                "status": terminal_status,
                "error": "restore failed" if terminal_status == "failed" else None,
                "command_results": [{"exit_code": 1 if terminal_status == "failed" else 0}],
            }

        runtime = AgentGuardRuntime(
            bootstrap_servers="kafka:9092",
            config=AgentGuardConfig(),
            llm=SimpleNamespace(request_timeout_seconds=None),
        )
        monkeypatch.setattr(runtime_module, "get_db", DbContextStub)
        monkeypatch.setattr(runtime_module, "SqlAlchemyAgentSessionRepository", lambda _db: repository)
        monkeypatch.setattr(runtime_module, "execute_rollback_request", execute)

        await runtime._handle_rollback_requested(request, SimpleNamespace())

        ledger = await repository.get_rollback(request["id"])
        assert ledger["status"] == terminal_status
        assert ledger["command_results"][0]["exit_code"] == (1 if terminal_status == "failed" else 0)

    anyio.run(run_test)


def test_json_consumer_start_stop_cancels_and_awaits_background_task(monkeypatch):
    async def run_test():
        consumer = LifecycleConsumerStub()
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)
        task = JsonKafkaConsumerTask("kafka:9092", "topic", "group", handler=None)

        await task.start()
        await asyncio.wait_for(consumer.started.wait(), timeout=1)

        assert task.task is not None
        assert not task.task.done()

        await task.stop()

        assert consumer.start_calls == 1
        assert consumer.stop_calls == 1
        assert task.task.done()
        assert task.task.cancelled()
        pending = [
            candidate
            for candidate in asyncio.all_tasks()
            if candidate is not asyncio.current_task() and not candidate.done()
        ]
        assert pending == []

    anyio.run(run_test)


def test_json_consumer_stop_waits_for_active_thread_handler(monkeypatch):
    async def run_test():
        started = threading.Event()
        release = threading.Event()
        consumer = ActiveLifecycleConsumerStub(
            [SimpleNamespace(value=b'{"run_id":"run-active"}')]
        )
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)

        async def handler(_payload, _cancellation_token):
            def analyze():
                started.set()
                release.wait(timeout=2)

            await asyncio.to_thread(analyze)

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=handler,
            drain_timeout_seconds=1,
        )
        await task.start()
        await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)

        stop_task = asyncio.create_task(task.stop())
        await asyncio.sleep(0)

        assert not stop_task.done()
        assert task.task is not None
        assert not task.task.cancelled()

        release.set()
        await asyncio.wait_for(stop_task, timeout=1)

        assert consumer.commits == 1
        assert consumer.stop_calls == 1
        assert task.task.done()
        assert not task.task.cancelled()

    anyio.run(run_test)


def test_stop_allows_active_handler_to_finish_before_drain_deadline(monkeypatch):
    async def run_test():
        started = asyncio.Event()
        release = asyncio.Event()
        consumer = ActiveLifecycleConsumerStub(
            [SimpleNamespace(value=b'{"run_id":"run-graceful"}')]
        )
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)

        async def handler(_payload, cancellation_token):
            started.set()
            await release.wait()
            cancellation_token.raise_if_cancelled()

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=handler,
            drain_timeout_seconds=1,
        )
        await task.start()
        await asyncio.wait_for(started.wait(), timeout=1)

        stop_task = asyncio.create_task(task.stop())
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(stop_task, timeout=1)

        assert consumer.commits == 1
        assert task.task is not None
        assert not task.task.cancelled()

    anyio.run(run_test)


def test_json_consumer_stop_cancels_awaiter_after_drain_timeout(monkeypatch, caplog):
    async def run_test():
        started = threading.Event()
        release = threading.Event()
        consumer = ActiveLifecycleConsumerStub(
            [SimpleNamespace(value=b'{"run_id":"run-timeout"}')]
        )
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)

        async def handler(_payload, _cancellation_token):
            def analyze():
                started.set()
                release.wait(timeout=2)

            await asyncio.to_thread(analyze)

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=handler,
            drain_timeout_seconds=0.01,
        )
        await task.start()
        await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)

        try:
            await asyncio.wait_for(task.stop(), timeout=0.5)
        finally:
            release.set()

        assert consumer.commits == 0
        assert consumer.stop_calls == 1
        assert task.task.done()
        assert task.task.cancelled()
        assert any(
            record.levelname == "ERROR" and "worker thread may continue" in record.getMessage()
            for record in caplog.records
        )

    anyio.run(run_test)


def test_json_consumer_stop_does_not_start_retry_after_active_handler_fails(monkeypatch):
    async def run_test():
        started = asyncio.Event()
        release = asyncio.Event()
        attempts = 0
        consumer = ActiveLifecycleConsumerStub(
            [SimpleNamespace(value=b'{"run_id":"run-stopping"}')]
        )
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)

        async def handler(_payload, _cancellation_token):
            nonlocal attempts
            attempts += 1
            started.set()
            await release.wait()
            raise RuntimeError("analysis failed during shutdown")

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "topic",
            "group",
            handler=handler,
            max_handler_attempts=3,
            retry_backoff_seconds=1,
            drain_timeout_seconds=1,
        )
        await task.start()
        await asyncio.wait_for(started.wait(), timeout=1)

        stop_task = asyncio.create_task(task.stop())
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(stop_task, timeout=1)

        assert attempts == 1
        assert consumer.commits == 0
        assert consumer.stop_calls == 1

    anyio.run(run_test)


def test_session_handler_deadline_cancels_graph_before_later_llm_calls(tmp_path, monkeypatch):
    async def run_test():
        diff = (
            "diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print('a')\n"
            "diff --git a/b.py b/b.py\n+++ b/b.py\n@@\n+print('b')\n"
        )
        diff_path = tmp_path / "deadline.diff"
        diff_path.write_text(diff, encoding="utf-8")
        llm_started = threading.Event()
        llm_release = threading.Event()
        analysis_finished = threading.Event()

        class BlockingLLM:
            def __init__(self):
                self.prompts = []

            def complete(self, prompt):
                self.prompts.append(prompt)
                llm_started.set()
                llm_release.wait(timeout=2)
                return '{"path":"a.py","summary":"a","risk_level":"low","findings":[]}'

        llm = BlockingLLM()
        repository = InMemoryAgentSessionRepository()
        session_handler = AgentSessionEventHandler(
            repository=repository,
            config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
            llm=llm,
        )
        import ai_agent.agent_guard.consumer as consumer_module

        real_process = consumer_module.process_finished_session_event

        def tracked_process(*args, **kwargs):
            try:
                return real_process(*args, **kwargs)
            finally:
                analysis_finished.set()

        monkeypatch.setattr(consumer_module, "process_finished_session_event", tracked_process)

        async def handler(event, cancellation_token):
            await session_handler.handle(event, cancellation_token=cancellation_token)

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "agent.session.finished",
            "session-group",
            handler=handler,
            max_handler_attempts=3,
            handler_timeout_seconds=0.2,
        )
        task.running = True
        event = {
            "run_id": "deadline-run",
            "original_request": "modify files",
            "diff_ref": {
                "storage": "local",
                "uri": str(diff_path),
                "sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            },
        }

        handled = await asyncio.wait_for(task._handle_message(event), timeout=1)

        assert handled is False
        assert task.running is False
        assert llm_started.is_set()
        llm_release.set()
        await asyncio.wait_for(asyncio.to_thread(analysis_finished.wait, 1), timeout=2)
        assert len(llm.prompts) == 1
        assert await repository.get_session("deadline-run") is None

    anyio.run(run_test)


def test_stop_during_retry_backoff_does_not_start_another_handler(monkeypatch):
    async def run_test():
        backoff_started = asyncio.Event()
        release_backoff = asyncio.Event()
        attempts = 0

        async def handler(_payload, _cancellation_token):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("retryable failure")

        async def controlled_backoff(_delay):
            backoff_started.set()
            await release_backoff.wait()

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "agent.session.finished",
            "session-group",
            handler=handler,
            max_handler_attempts=3,
            retry_backoff_seconds=1,
        )
        task.running = True
        monkeypatch.setattr(asyncio, "sleep", controlled_backoff)

        handling = asyncio.create_task(task._handle_message({"run_id": "run-stopping"}))
        await asyncio.wait_for(backoff_started.wait(), timeout=1)
        task.running = False
        release_backoff.set()

        assert await asyncio.wait_for(handling, timeout=1) is False
        assert attempts == 1

    anyio.run(run_test)


def test_stop_drain_timeout_cancels_remaining_file_analysis(tmp_path, monkeypatch):
    async def run_test():
        diff = (
            "diff --git a/a.py b/a.py\n+++ b/a.py\n@@\n+print('a')\n"
            "diff --git a/b.py b/b.py\n+++ b/b.py\n@@\n+print('b')\n"
        )
        diff_path = tmp_path / "stop.diff"
        diff_path.write_text(diff, encoding="utf-8")
        llm_started = threading.Event()
        llm_release = threading.Event()
        analysis_finished = threading.Event()

        class BlockingLLM:
            def __init__(self):
                self.prompts = []

            def complete(self, prompt):
                self.prompts.append(prompt)
                llm_started.set()
                llm_release.wait(timeout=2)
                return '{"path":"a.py","summary":"a","risk_level":"low","findings":[]}'

        import ai_agent.agent_guard.consumer as consumer_module

        real_process = consumer_module.process_finished_session_event

        def tracked_process(*args, **kwargs):
            try:
                return real_process(*args, **kwargs)
            finally:
                analysis_finished.set()

        monkeypatch.setattr(consumer_module, "process_finished_session_event", tracked_process)
        llm = BlockingLLM()
        session_handler = AgentSessionEventHandler(
            repository=InMemoryAgentSessionRepository(),
            config=AgentGuardConfig(small_diff_token_limit=1, medium_diff_token_limit=1000),
            llm=llm,
        )
        event = {
            "run_id": "stop-run",
            "original_request": "modify files",
            "diff_ref": {
                "storage": "local",
                "uri": str(diff_path),
                "sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
            },
        }
        consumer = ActiveLifecycleConsumerStub([SimpleNamespace(value=event)])
        monkeypatch.setattr(runtime_module, "AIOKafkaConsumer", lambda *_args, **_kwargs: consumer)

        async def handler(payload, cancellation_token):
            await session_handler.handle(payload, cancellation_token=cancellation_token)

        task = JsonKafkaConsumerTask(
            "kafka:9092",
            "agent.session.finished",
            "session-group",
            handler=handler,
            drain_timeout_seconds=0.01,
        )
        await task.start()
        await asyncio.wait_for(asyncio.to_thread(llm_started.wait, 1), timeout=2)

        await asyncio.wait_for(task.stop(), timeout=0.5)
        llm_release.set()
        await asyncio.wait_for(asyncio.to_thread(analysis_finished.wait, 1), timeout=2)

        assert len(llm.prompts) == 1
        assert consumer.commits == 0

    anyio.run(run_test)
