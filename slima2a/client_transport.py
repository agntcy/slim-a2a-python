# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Callable

import slim_bindings
from a2a.client.client import ClientCallContext
from a2a.client.client import ClientConfig as A2AClientConfig
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


@dataclass
class ClientConfig(A2AClientConfig):
    slimrpc_channel_factory: Callable[[str], slim_bindings.Channel] | None = None


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
