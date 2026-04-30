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
        card: AgentCard,
        url: str,
        config: ClientConfig,
    ) -> "SRPCTransport":
        """Creates a SlimRPC transport for the A2A client."""
        if config.slimrpc_channel_factory is None:
            raise ValueError("slimrpc_channel_factory is required when using sRPC")
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


class SRPCClientFactory(ClientFactory):
    """Client factory that extends the standard A2A ClientFactory with multicast support.

    Uses the agent card's interface URL to determine unicast vs multicast:
    - Single name (e.g. "agntcy/demo/agent1") -> unicast Client
    - Comma-separated names (e.g. "agntcy/demo/agent1,agntcy/demo/agent2") -> MulticastClient

    Usage:
        factory = SRPCClientFactory(client_config)
        # Unicast
        client = factory.create(card=minimal_agent_card("agntcy/demo/agent1", ["slimrpc"]))
        # Multicast
        client = factory.create(card=minimal_agent_card("agntcy/demo/agent1,agntcy/demo/agent2", ["slimrpc"]))
    """

    def __init__(
        self,
        config: ClientConfig,
        consumers: list | None = None,
    ) -> None:
        super().__init__(config, consumers)
        self._config: ClientConfig = config
        self.register("slimrpc", SRPCTransport.create)  # type: ignore[arg-type]

    def create(  # type: ignore[override]
        self,
        card: AgentCard,
        consumers: list | None = None,
        interceptors: list | None = None,
    ) -> "Client | MulticastClient":
        """Creates a client for the given agent card.

        If the card's slimrpc interface URL contains multiple comma-separated
        agent names, a MulticastClient is returned. Otherwise, a standard
        unicast Client is returned.
        """
        for interface in card.supported_interfaces:
            if interface.protocol_binding == "slimrpc" and "," in interface.url:
                agent_names = [name.strip() for name in interface.url.split(",")]
                return MulticastClient.create(agent_names, self._config)

        return super().create(card, consumers, interceptors)


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

    def __init__(self, transport: SRPCMulticastTransport, config: ClientConfig) -> None:
        self._transport = transport
        self._config = config

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
        return cls(transport, config)

    async def send_message(
        self,
        request: SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[tuple[Any, StreamResponse], None]:
        """Sends a message to all agents in the group.

        Like the unicast Client.send_message, this always yields StreamResponse
        objects. When streaming is enabled, it uses the streaming RPC and yields
        interleaved chunks. Otherwise, it uses the unary RPC and wraps each
        SendMessageResponse into a StreamResponse.
        """
        if self._config.streaming:
            async for source, response in self._transport.send_message_streaming(
                request, context=context
            ):
                yield source, response
        else:
            async for source, response in self._transport.send_message(
                request, context=context
            ):
                stream_response = StreamResponse()
                if response.HasField("task"):
                    stream_response.task.CopyFrom(response.task)
                elif response.HasField("message"):
                    stream_response.message.CopyFrom(response.message)
                yield source, stream_response

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
