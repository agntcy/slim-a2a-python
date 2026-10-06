# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""The ACTS SUT behaviors (`tck-*` prefixes) as a plain a2a-sdk executor.

The ACTS corpus drives the system under test by the first word of a message:
`tck-complete-task hello` asks for a completed task, `tck-multi-turn start`
opens a conversation, and so on. The set this executor implements is declared
in `acts/sut-behaviors.yaml` at the repo root, which the ITK runner reads to
decide which tests the SDK is graded on.

Nothing here is SLIM-specific. The executor sits behind every binding the ITK
agent serves, which is what makes a SLIM run directly comparable to a
JSON-RPC or gRPC run of the same agent.
"""

import asyncio
import logging

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Message, Part, Role, TaskState
from google.protobuf.struct_pb2 import Struct, Value

logger = logging.getLogger(__name__)

#: How long `tck-long-running` works before completing. ACTS polls for up to
#: 30s, so this leaves room for a slow CI box without making runs drag.
LONG_RUNNING_SECONDS = 3.0

#: How long `tck-cancel` works if nobody cancels it. Long enough that the
#: corpus's cancel step always lands while the task is still running.
CANCELABLE_SECONDS = 60.0

#: Pause between streamed events, so `tck-stream-basic` produces a genuine
#: sequence rather than one burst the transport might coalesce.
STREAM_STEP_SECONDS = 0.1

#: Artifact id `tck-stream-chunked` streams its chunks under.
CHUNKED_ARTIFACT_ID = "tck-chunked"

#: The reply to a multi-turn follow-up that ends the conversation.
MULTI_TURN_DONE = "done"


def _prefix(context: RequestContext) -> str:
    """The `tck-*` prefix a message asks for, or `""` when it has none."""
    text = context.get_user_input().strip()
    first = text.split(maxsplit=1)[0] if text else ""
    return first if first.startswith("tck-") else ""


class TckAgentExecutor(AgentExecutor):
    """Implements the `tck-*` behaviors the ACTS corpus exercises."""

    def __init__(self) -> None:
        # Signalled by `cancel` so a running `tck-cancel` stops promptly
        # instead of finishing its sleep and then trying to complete.
        self._cancelled: dict[str, asyncio.Event] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ValueError("ACTS behaviors need a message")

        prefix = _prefix(context)

        if prefix == "tck-message-response":
            # A bare message, never a task (CORE-SEND-003, DM-FMT-003).
            await event_queue.enqueue_event(
                Message(
                    role=Role.ROLE_AGENT,
                    message_id=f"{context.message.message_id}-reply",
                    context_id=context.context_id or "",
                    parts=[Part(text=f"{prefix} response")],
                )
            )
            return

        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # A follow-up on a task waiting for input carries no prefix of its
        # own ("here is more input", "done"), so it continues the multi-turn
        # conversation that task belongs to.
        if not prefix and task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
            prefix = "tck-multi-turn"

        match prefix:
            case "tck-complete-task" | "":
                await updater.complete(self._reply(updater, "completed"))
            case "tck-multi-turn":
                if context.get_user_input().strip().lower() == MULTI_TURN_DONE:
                    await updater.complete(self._reply(updater, "conversation done"))
                else:
                    await updater.requires_input(
                        self._reply(updater, "need more input")
                    )
            case "tck-long-running":
                await updater.start_work()
                await asyncio.sleep(LONG_RUNNING_SECONDS)
                await updater.complete(self._reply(updater, "long-running done"))
            case "tck-cancel":
                await self._cancelable(task.id, updater)
            case "tck-task-failure":
                await updater.failed(self._reply(updater, "requested failure"))
            case "tck-auth-required":
                await updater.requires_auth(
                    self._reply(updater, "authentication required")
                )
            case "tck-stream-basic":
                await updater.start_work(self._reply(updater, "streaming"))
                await asyncio.sleep(STREAM_STEP_SECONDS)
                await updater.add_artifact(
                    [Part(text="streamed output")], name="output"
                )
                await asyncio.sleep(STREAM_STEP_SECONDS)
                await updater.complete(self._reply(updater, "stream done"))
            case "tck-stream-chunked":
                # One artifact delivered in two chunks: the second appends to
                # the first and closes it (A2A artifact-update `append` /
                # `lastChunk`).
                await updater.start_work()
                await asyncio.sleep(STREAM_STEP_SECONDS)
                await updater.add_artifact(
                    [Part(text="chunk one, ")],
                    artifact_id=CHUNKED_ARTIFACT_ID,
                    name="chunked",
                    append=False,
                    last_chunk=False,
                )
                await asyncio.sleep(STREAM_STEP_SECONDS)
                await updater.add_artifact(
                    [Part(text="chunk two")],
                    artifact_id=CHUNKED_ARTIFACT_ID,
                    append=True,
                    last_chunk=True,
                )
                await updater.complete()
            case "tck-artifact-text":
                await updater.add_artifact([Part(text="artifact text")], name="text")
                await updater.complete()
            case "tck-artifact-data":
                data = Struct()
                data.update({"kind": "tck-artifact-data", "value": 42})
                await updater.add_artifact(
                    [Part(data=Value(struct_value=data))], name="data"
                )
                await updater.complete()
            case "tck-artifact-file":
                part = Part(
                    raw=b"tck artifact file",
                    filename="tck.txt",
                    media_type="text/plain",
                )
                await updater.add_artifact([part], name="file")
                await updater.complete()
            case "tck-artifact-file-url":
                part = Part(
                    url="https://example.com/tck.txt",
                    filename="tck.txt",
                    media_type="text/plain",
                )
                await updater.add_artifact([part], name="file-url")
                await updater.complete()
            case _:
                # An unknown prefix is the corpus asking for something this
                # SUT never claimed in sut-behaviors.yaml; fail visibly.
                await updater.failed(self._reply(updater, f"unknown behavior {prefix}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id or ""
        if event := self._cancelled.get(task_id):
            event.set()
        updater = TaskUpdater(event_queue, task_id, context.context_id or "")
        await updater.cancel()

    async def _cancelable(self, task_id: str, updater: TaskUpdater) -> None:
        event = self._cancelled.setdefault(task_id, asyncio.Event())
        await updater.start_work()
        try:
            await asyncio.wait_for(event.wait(), timeout=CANCELABLE_SECONDS)
        except asyncio.TimeoutError:
            await updater.complete(self._reply(updater, "nobody cancelled"))
        finally:
            self._cancelled.pop(task_id, None)

    @staticmethod
    def _reply(updater: TaskUpdater, text: str) -> Message:
        return updater.new_agent_message([Part(text=text)])
