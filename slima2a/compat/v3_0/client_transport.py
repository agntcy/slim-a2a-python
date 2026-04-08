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
from a2a.compat.v0_3 import (
    a2a_v0_3_pb2,
    conversions,
    proto_utils,
)
from a2a.compat.v0_3 import types as types_v03
from a2a.types import a2a_pb2
from a2a.utils.constants import PROTOCOL_VERSION_0_3, VERSION_HEADER
from a2a.utils.telemetry import SpanKind, trace_class

from slima2a.types.v0 import a2a_pb2_slimrpc

logger = logging.getLogger(__name__)


@dataclass
class ClientConfig(A2AClientConfig):
    slimrpc_channel_factory: Callable[[str], slim_bindings.Channel] | None = None


@trace_class(kind=SpanKind.CLIENT)
class SRPCCompatTransport(ClientTransport):
    """A backward compatible SlimRPC transport for A2A v0.3."""

    def __init__(
        self,
        channel: slim_bindings.Channel,
        agent_card: a2a_pb2.AgentCard | None,
    ) -> None:
        """Initializes the SRPCCompatTransport."""
        self.agent_card = agent_card
        self.channel = channel
        self.stub = a2a_pb2_slimrpc.A2AServiceStub(channel)

    @classmethod
    def create(
        cls,
        card: a2a_pb2.AgentCard,
        url: str,
        config: ClientConfig,
    ) -> "SRPCCompatTransport":
        """Creates a SlimRPC compat transport for the A2A client."""
        if config.slimrpc_channel_factory is None:
            raise ValueError("slimrpc_channel_factory is required when using sRPC")
        channel = config.slimrpc_channel_factory(url)
        return cls(channel, card)

    def _get_metadata(self, context: ClientCallContext | None = None) -> dict[str, str]:
        """Creates SlimRPC metadata for the request."""
        metadata: dict[str, str] = {VERSION_HEADER: PROTOCOL_VERSION_0_3}
        if context and context.service_parameters:
            for key, value in context.service_parameters.items():
                metadata[key] = value
        return metadata

    async def send_message(
        self,
        request: a2a_pb2.SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.SendMessageResponse:
        """Sends a non-streaming message request to the agent (v0.3)."""
        req_v03 = conversions.to_compat_send_message_request(request, request_id=0)
        req_proto = a2a_v0_3_pb2.SendMessageRequest(
            request=proto_utils.ToProto.message(req_v03.params.message),
            configuration=proto_utils.ToProto.message_send_configuration(
                req_v03.params.configuration
            ),
            metadata=proto_utils.ToProto.metadata(req_v03.params.metadata),
        )
        resp_proto = await self.stub.SendMessage(
            req_proto,
            metadata=self._get_metadata(context),
        )
        which = resp_proto.WhichOneof("payload")
        if which == "task":
            return a2a_pb2.SendMessageResponse(
                task=conversions.to_core_task(
                    proto_utils.FromProto.task(resp_proto.task)
                )
            )
        if which == "msg":
            return a2a_pb2.SendMessageResponse(
                message=conversions.to_core_message(
                    proto_utils.FromProto.message(resp_proto.msg)
                )
            )
        return a2a_pb2.SendMessageResponse()

    async def send_message_streaming(
        self,
        request: a2a_pb2.SendMessageRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[a2a_pb2.StreamResponse, None]:
        """Sends a streaming message request to the agent (v0.3)."""
        req_v03 = conversions.to_compat_send_message_request(request, request_id=0)
        req_proto = a2a_v0_3_pb2.SendMessageRequest(
            request=proto_utils.ToProto.message(req_v03.params.message),
            configuration=proto_utils.ToProto.message_send_configuration(
                req_v03.params.configuration
            ),
            metadata=proto_utils.ToProto.metadata(req_v03.params.metadata),
        )
        async for response in self.stub.SendStreamingMessage(
            req_proto,
            metadata=self._get_metadata(context),
        ):
            yield conversions.to_core_stream_response(
                types_v03.SendStreamingMessageSuccessResponse(
                    result=proto_utils.FromProto.stream_response(response)
                )
            )

    async def subscribe(
        self,
        request: a2a_pb2.SubscribeToTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> AsyncGenerator[a2a_pb2.StreamResponse, None]:
        """Reconnects to get task updates (v0.3)."""
        req_proto = a2a_v0_3_pb2.TaskSubscriptionRequest(name=f"tasks/{request.id}")
        async for response in self.stub.TaskSubscription(
            req_proto,
            metadata=self._get_metadata(context),
        ):
            yield conversions.to_core_stream_response(
                types_v03.SendStreamingMessageSuccessResponse(
                    result=proto_utils.FromProto.stream_response(response)
                )
            )

    async def get_task(
        self,
        request: a2a_pb2.GetTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.Task:
        """Retrieves the current state and history of a specific task (v0.3)."""
        req_proto = a2a_v0_3_pb2.GetTaskRequest(
            name=f"tasks/{request.id}",
            history_length=request.history_length,
        )
        resp_proto = await self.stub.GetTask(
            req_proto,
            metadata=self._get_metadata(context),
        )
        return conversions.to_core_task(proto_utils.FromProto.task(resp_proto))

    async def list_tasks(
        self,
        request: a2a_pb2.ListTasksRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.ListTasksResponse:
        """Not supported in A2A v0.3."""
        raise NotImplementedError("ListTasks is not supported in A2A v0.3 SlimRPC.")

    async def cancel_task(
        self,
        request: a2a_pb2.CancelTaskRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.Task:
        """Requests the agent to cancel a specific task (v0.3)."""
        req_proto = a2a_v0_3_pb2.CancelTaskRequest(name=f"tasks/{request.id}")
        resp_proto = await self.stub.CancelTask(
            req_proto,
            metadata=self._get_metadata(context),
        )
        return conversions.to_core_task(proto_utils.FromProto.task(resp_proto))

    async def create_task_push_notification_config(
        self,
        request: a2a_pb2.TaskPushNotificationConfig,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.TaskPushNotificationConfig:
        """Sets or updates the push notification configuration (v0.3)."""
        req_v03 = conversions.to_compat_create_task_push_notification_config_request(
            request, request_id=0
        )
        req_proto = a2a_v0_3_pb2.CreateTaskPushNotificationConfigRequest(
            parent=f"tasks/{request.task_id}",
            config_id=req_v03.params.push_notification_config.id,
            config=proto_utils.ToProto.task_push_notification_config(req_v03.params),
        )
        resp_proto = await self.stub.CreateTaskPushNotificationConfig(
            req_proto,
            metadata=self._get_metadata(context),
        )
        return conversions.to_core_task_push_notification_config(
            proto_utils.FromProto.task_push_notification_config(resp_proto)
        )

    async def get_task_push_notification_config(
        self,
        request: a2a_pb2.GetTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.TaskPushNotificationConfig:
        """Retrieves the push notification configuration (v0.3)."""
        req_proto = a2a_v0_3_pb2.GetTaskPushNotificationConfigRequest(
            name=f"tasks/{request.task_id}/pushNotificationConfigs/{request.id}"
        )
        resp_proto = await self.stub.GetTaskPushNotificationConfig(
            req_proto,
            metadata=self._get_metadata(context),
        )
        return conversions.to_core_task_push_notification_config(
            proto_utils.FromProto.task_push_notification_config(resp_proto)
        )

    async def list_task_push_notification_configs(
        self,
        request: a2a_pb2.ListTaskPushNotificationConfigsRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.ListTaskPushNotificationConfigsResponse:
        """Lists push notification configurations for a specific task (v0.3)."""
        req_proto = a2a_v0_3_pb2.ListTaskPushNotificationConfigRequest(
            parent=f"tasks/{request.task_id}"
        )
        resp_proto = await self.stub.ListTaskPushNotificationConfig(
            req_proto,
            metadata=self._get_metadata(context),
        )
        return conversions.to_core_list_task_push_notification_config_response(
            proto_utils.FromProto.list_task_push_notification_config_response(
                resp_proto
            )
        )

    async def delete_task_push_notification_config(
        self,
        request: a2a_pb2.DeleteTaskPushNotificationConfigRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> None:
        """Deletes the push notification configuration (v0.3)."""
        req_proto = a2a_v0_3_pb2.DeleteTaskPushNotificationConfigRequest(
            name=f"tasks/{request.task_id}/pushNotificationConfigs/{request.id}"
        )
        await self.stub.DeleteTaskPushNotificationConfig(
            req_proto,
            metadata=self._get_metadata(context),
        )

    async def get_extended_agent_card(
        self,
        request: a2a_pb2.GetExtendedAgentCardRequest,
        *,
        context: ClientCallContext | None = None,
    ) -> a2a_pb2.AgentCard:
        """Retrieves the agent's card (v0.3)."""
        req_proto = a2a_v0_3_pb2.GetAgentCardRequest()
        resp_proto = await self.stub.GetAgentCard(
            req_proto,
            metadata=self._get_metadata(context),
        )
        card = conversions.to_core_agent_card(
            proto_utils.FromProto.agent_card(resp_proto)
        )
        self.agent_card = card
        return card

    async def close(self) -> None:
        """Closes the transport and releases any resources."""
        pass
