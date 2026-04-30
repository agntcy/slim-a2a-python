# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Callable

import slim_bindings
from a2a.client import Client
from a2a.client.client import ClientCallContext
from a2a.client.client import ClientConfig as A2AClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.client.transports.base import ClientTransport
from a2a.types.a2a_pb2 import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    SendMessageRequest,
    SendMessageResponse,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from a2a.utils.telemetry import SpanKind, trace_class

from slima2a.types.v1 import a2a_pb2_slimrpc

logger = logging.getLogger(__name__)


def slimrpc_channel_factory(
    local_app: slim_bindings.App,
    conn_id: int,
) -> Callable[[str], slim_bindings.Channel]:
    def factory(remote: str) -> slim_bindings.Channel:
        # Parse the remote name from the URL
        remote_parts = remote.split("/")
        if len(remote_parts) != 3:
            raise ValueError(
                f"Invalid remote format: '{remote}'. Expected format: 'component1/component2/component'"
            )

        remote_name = slim_bindings.Name(
            remote_parts[0], remote_parts[1], remote_parts[2]
        )

        return slim_bindings.Channel.new_with_connection(
            local_app, remote_name, conn_id
        )

    return factory


def slimrpc_group_channel_factory(
    local_app: slim_bindings.App,
    conn_id: int,
) -> Callable[[list[str]], slim_bindings.Channel]:
    def factory(remotes: list[str]) -> slim_bindings.Channel:
        members = []
        for remote in remotes:
            remote_parts = remote.split("/")
            if len(remote_parts) != 3:
                raise ValueError(
                    f"Invalid remote format: '{remote}'. Expected format: 'component1/component2/component'"
                )
            members.append(
                slim_bindings.Name(remote_parts[0], remote_parts[1], remote_parts[2])
            )

        return slim_bindings.Channel.new_group_with_connection(
            local_app, members, conn_id
        )

    return factory


@dataclass
class ClientConfig(A2AClientConfig):
    slimrpc_channel_factory: Callable[[str], slim_bindings.Channel] | None = None
    slimrpc_group_channel_factory: (
        Callable[[list[str]], slim_bindings.Channel] | None
    ) = None


@trace_class(kind=SpanKind.CLIENT)
class SRPCTransport(ClientTransport):
    """A SlimRPC transport for the A2A client."""

    def __init__(
        self,
        channel: slim_bindings.Channel,
        agent_card: AgentCard | None,
    ) -> None:
        """Initializes the SRPCTransport."""
        self.agent_card = agent_card
        self.channel = channel
        self.stub = a2a_pb2_slimrpc.A2AServiceStub(channel)

    @classmethod
    def create(
        cls,
        card: "AgentCard | list[AgentCard]",
        url: str | None = None,
        config: "ClientConfig | None" = None,
    ) -> "SRPCTransport | MulticastClient":
        """Creates a SlimRPC transport for single or multiple agents.

        When card is a single AgentCard, returns an SRPCTransport (unicast).
        When card is a list of AgentCards, returns a MulticastClient.
        """
        if isinstance(card, list):
            if config is None:
                raise ValueError("config is required when using sRPC multicast")
            urls: list[str] = []
            for c in card:
                iface = ClientFactory._find_best_interface(
                    list(c.supported_interfaces), protocol_bindings=["slimrpc"]
                )
                if not iface:
                    raise ValueError(f"Card '{c.name}' does not support slimrpc")
                urls.append(iface.url)
            return MulticastClient.create(urls, config)

        if config is None or config.slimrpc_channel_factory is None:
            raise ValueError("slimrpc_channel_factory is required when using sRPC")
        if url is None:
            raise ValueError("url is required for unicast sRPC")
        channel = config.slimrpc_channel_factory(url)
        return cls(channel, card)

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> SendMessageResponse:
        """Sends a non-streaming message request to the agent."""
        return await self.stub.SendMessage(request)

    async def send_message_streaming(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[StreamResponse, None]:
        """Sends a streaming message request to the agent and yields responses as they arrive."""
        async for response in self.stub.SendStreamingMessage(request):
            yield response

    async def subscribe(
        self,
        request: SubscribeToTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[StreamResponse, None]:
        """Reconnects to get task updates."""
        async for response in self.stub.SubscribeToTask(request):
            yield response

    async def get_task(
        self,
        request: GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task:
        """Retrieves the current state and history of a specific task."""
        return await self.stub.GetTask(request)

    async def list_tasks(
        self,
        request: ListTasksRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTasksResponse:
        """Retrieves tasks for an agent."""
        return await self.stub.ListTasks(request)

    async def cancel_task(
        self,
        request: CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> Task:
        """Requests the agent to cancel a specific task."""
        return await self.stub.CancelTask(request)

    async def create_task_push_notification_config(
        self,
        request: TaskPushNotificationConfig,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Sets or updates the push notification configuration for a specific task."""
        return await self.stub.CreateTaskPushNotificationConfig(request)

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> TaskPushNotificationConfig:
        """Retrieves the push notification configuration for a specific task."""
        return await self.stub.GetTaskPushNotificationConfig(request)

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> ListTaskPushNotificationConfigsResponse:
        """Lists push notification configurations for a specific task."""
        return await self.stub.ListTaskPushNotificationConfigs(request)

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        """Deletes the push notification configuration for a specific task."""
        await self.stub.DeleteTaskPushNotificationConfig(request)

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AgentCard:
        """Retrieves the agent's extended card."""
        card = self.agent_card
        if card and not card.capabilities.extended_agent_card:
            return card
        return await self.stub.GetExtendedAgentCard(request)

    async def close(self) -> None:
        """Closes the transport and releases any resources."""
        pass


class MultiAgentClientFactory(ClientFactory):
    """
    An extension of ClientFactory that supports sending messages to multiple Agents simultaneously.

    Will find a common transport in the intersection of Agent's supported interfaces
    which supports multi agent communication and use that. Otherwise falls back to
    individual clients (TODO).

    Usage:
        factory = MultiAgentClientFactory(client_config)
        factory.register("slimrpc", SRPCTransport.create, multiagent=True)
        # Unicast
        client = factory.create(card=agent_card)
        # Multicast
        client = factory.create(card=[card1, card2, card3])
    """

    def __init__(
        self,
        config: ClientConfig,
        consumers: list | None = None,
    ) -> None:
        super().__init__(config, consumers)
        self._config: ClientConfig = config
        self._multiagent_labels: set[str] = set()
        self.register("slimrpc", SRPCTransport.create, multiagent=True)  # type: ignore[arg-type]

    def register(  # type: ignore[override]
        self,
        label: str,
        producer: Callable[..., Any],
        multiagent: bool = False,
    ) -> None:
        if multiagent:
            self._multiagent_labels.add(label)
        super().register(label, producer)

    def create(  # type: ignore[override]
        self,
        card: AgentCard | list[AgentCard],
        consumers: list | None = None,
        interceptors: list | None = None,
    ) -> "Client | MulticastClient":
        if not isinstance(card, list):
            return super().create(card, consumers, interceptors)

        if len(card) == 1:
            return super().create(card[0], consumers, interceptors)

        protocol = self._find_common_multiagent_protocol(card)
        producer = self._registry[protocol]
        return producer(card, None, self._config)  # type: ignore[arg-type, return-value]

    def _find_common_multiagent_protocol(self, cards: list[AgentCard]) -> str:
        per_card = [{i.protocol_binding for i in c.supported_interfaces} for c in cards]
        common = set.intersection(*per_card)

        preferred = self._config.supported_protocol_bindings or list(
            self._multiagent_labels
        )
        for protocol in preferred:
            if protocol in common and protocol in self._multiagent_labels:
                return protocol

        raise ValueError(
            f"No common multiagent-capable protocol. Common: {common}, "
            f"Multiagent-capable: {self._multiagent_labels}"
        )


@trace_class(kind=SpanKind.CLIENT)
class SRPCMulticastTransport:
    """A SlimRPC multicast transport for querying multiple A2A agents simultaneously.

    All methods are async generators that yield (source, response) tuples,
    where source is the context identifying which agent produced the response.
    """

    def __init__(
        self,
        channel: slim_bindings.Channel,
    ) -> None:
        self.channel = channel
        self.stub = a2a_pb2_slimrpc.A2AServiceGroupStub(channel)

    @classmethod
    def create(
        cls,
        agent_names: list[str],
        config: ClientConfig,
    ) -> "SRPCMulticastTransport":
        """Creates a multicast transport targeting multiple agents."""
        if config.slimrpc_group_channel_factory is None:
            raise ValueError(
                "slimrpc_group_channel_factory is required when using sRPC multicast"
            )
        channel = config.slimrpc_group_channel_factory(agent_names)
        return cls(channel)

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, SendMessageResponse], None]:
        async for source, response in self.stub.SendMessage(request):
            yield source, response

    async def send_message_streaming(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        async for source, response in self.stub.SendStreamingMessage(request):
            yield source, response

    async def get_task(
        self,
        request: GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, Task], None]:
        async for source, response in self.stub.GetTask(request):
            yield source, response

    async def list_tasks(
        self,
        request: ListTasksRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, ListTasksResponse], None]:
        async for source, response in self.stub.ListTasks(request):
            yield source, response

    async def cancel_task(
        self,
        request: CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, Task], None]:
        async for source, response in self.stub.CancelTask(request):
            yield source, response

    async def subscribe(
        self,
        request: SubscribeToTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        async for source, response in self.stub.SubscribeToTask(request):
            yield source, response

    async def create_task_push_notification_config(
        self,
        request: TaskPushNotificationConfig,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, TaskPushNotificationConfig], None]:
        async for source, response in self.stub.CreateTaskPushNotificationConfig(
            request
        ):
            yield source, response

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, TaskPushNotificationConfig], None]:
        async for source, response in self.stub.GetTaskPushNotificationConfig(request):
            yield source, response

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, ListTaskPushNotificationConfigsResponse], None]:
        async for source, response in self.stub.ListTaskPushNotificationConfigs(
            request
        ):
            yield source, response

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, None], None]:
        async for source, _ in self.stub.DeleteTaskPushNotificationConfig(request):
            yield source, None

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, AgentCard], None]:
        async for source, response in self.stub.GetExtendedAgentCard(request):
            yield source, response

    async def close(self) -> None:
        """Closes the transport and releases any resources."""
        pass


class MulticastClient:
    """A2A client for querying multiple agents simultaneously via sRPC multicast.

    All methods are async generators that yield (source, response) tuples,
    where source identifies which agent produced the response.
    """

    def __init__(self, transport: SRPCMulticastTransport) -> None:
        self._transport = transport

    @classmethod
    def create(
        cls,
        agent_names: list[str],
        config: ClientConfig,
    ) -> "MulticastClient":
        """Creates a multicast client targeting multiple agents.

        Args:
            agent_names: List of SLIM agent names (e.g., ["agntcy/demo/agent1", "agntcy/demo/agent2"]).
            config: Client configuration with slimrpc_group_channel_factory set.
        """
        transport = SRPCMulticastTransport.create(agent_names, config)
        return cls(transport)

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        """Sends a message to all agents in the group.

        Yields (source, response) tuples — one complete response per agent,
        wrapped as StreamResponse.
        """
        async for source, response in self._transport.send_message(
            request, context=context
        ):
            stream_response = StreamResponse()
            if response.HasField("task"):
                stream_response.task.CopyFrom(response.task)
            elif response.HasField("message"):
                stream_response.message.CopyFrom(response.message)
            yield source, stream_response

    async def send_message_streaming(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        """Sends a streaming message to all agents in the group.

        Yields interleaved (source, chunk) tuples as StreamResponse chunks
        arrive from any agent. Use ``source`` to demultiplex per-agent.
        """
        async for source, response in self._transport.send_message_streaming(
            request, context=context
        ):
            yield source, response

    async def get_task(
        self,
        request: GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, Task], None]:
        async for source, response in self._transport.get_task(
            request, context=context
        ):
            yield source, response

    async def list_tasks(
        self,
        request: ListTasksRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, ListTasksResponse], None]:
        async for source, response in self._transport.list_tasks(
            request, context=context
        ):
            yield source, response

    async def cancel_task(
        self,
        request: CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, Task], None]:
        async for source, response in self._transport.cancel_task(
            request, context=context
        ):
            yield source, response

    async def subscribe(
        self,
        request: SubscribeToTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        async for source, response in self._transport.subscribe(
            request, context=context
        ):
            yield source, response

    async def create_task_push_notification_config(
        self,
        request: TaskPushNotificationConfig,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, TaskPushNotificationConfig], None]:
        async for (
            source,
            response,
        ) in self._transport.create_task_push_notification_config(
            request, context=context
        ):
            yield source, response

    async def get_task_push_notification_config(
        self,
        request: GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, TaskPushNotificationConfig], None]:
        async for source, response in self._transport.get_task_push_notification_config(
            request, context=context
        ):
            yield source, response

    async def list_task_push_notification_configs(
        self,
        request: ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, ListTaskPushNotificationConfigsResponse], None]:
        async for (
            source,
            response,
        ) in self._transport.list_task_push_notification_configs(
            request, context=context
        ):
            yield source, response

    async def delete_task_push_notification_config(
        self,
        request: DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, None], None]:
        async for (
            source,
            response,
        ) in self._transport.delete_task_push_notification_config(
            request, context=context
        ):
            yield source, response

    async def get_extended_agent_card(
        self,
        request: GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, AgentCard], None]:
        async for source, response in self._transport.get_extended_agent_card(
            request, context=context
        ):
            yield source, response

    async def close(self) -> None:
        await self._transport.close()

    async def __aenter__(self) -> "MulticastClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
