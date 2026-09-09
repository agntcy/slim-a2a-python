import logging

logger = logging.getLogger(__name__)

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.agent_execution.agent_input_queue import AgentInputQueue
from a2a.server.events import EventQueue
from a2a.server.events.event_queue_v2 import QueueShutDown
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Message, Part, Role

from examples.echo_agent.echo_agent import EchoAgent


class EchoAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.agent = EchoAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        input_queue: AgentInputQueue,
    ) -> None:
        task_updater: TaskUpdater | None = None

        while True:
            try:
                turn = await input_queue.get()
            except QueueShutDown:
                break

            if not turn.message:
                continue

            # slim-src is set only on peer-translated messages (per spec §6);
            # direct client messages never carry it — use its presence to skip peers
            msg_src = turn.metadata.get("slim-src")
            if msg_src:
                logger.info(f"skipping peer message from {msg_src}")
                continue

            logger.info(f"received message: {turn.message}")

            if task_updater is None:
                # First turn: bootstrap the task
                if not turn.message.task_id or not turn.message.context_id:
                    raise Exception("invalid message")
                task = turn.current_task
                if task is None:
                    task = new_task_from_user_message(turn.message)
                    await event_queue.enqueue_event(task)
                task_updater = TaskUpdater(
                    event_queue=event_queue,
                    task_id=task.id,
                    context_id=task.context_id,
                )

            if turn.message.parts[0].WhichOneof("content") != "text":
                logger.warning("skipping non-text message part")
                continue

            result = await self.agent.invoke(turn.message.parts[0].text)

            response = Message(
                role=Role.ROLE_AGENT,
                message_id=turn.message.message_id,
                parts=[Part(text=result)],
            )
            await task_updater.add_artifact(
                parts=list(response.parts),
                name="result",
            )

        if task_updater is not None:
            await task_updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel not supported")
