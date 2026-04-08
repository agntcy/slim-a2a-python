# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

# ruff: noqa: N802
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Callable

import slim_bindings
from a2a.auth.user import UnauthenticatedUser
from a2a.compat.v0_3 import (
    a2a_v0_3_pb2,
    conversions,
    proto_utils,
)
from a2a.compat.v0_3 import types as types_v03
from a2a.compat.v0_3.request_handler import RequestHandler03
from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types.a2a_pb2 import AgentCard
from a2a.utils.errors import (
    A2AError,
    ContentTypeNotSupportedError,
    InternalError,
    InvalidAgentResponseError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from google.protobuf import empty_pb2
from google.rpc import code_pb2

from slima2a.types.v0 import a2a_pb2_slimrpc

logger = logging.getLogger(__name__)

SlimRPCError = slim_bindings.RpcError.Rpc  # type: ignore[attr-defined]

_SLIM_ERROR_CODE_MAP: dict[type[A2AError], int] = {
    InvalidRequestError: code_pb2.INVALID_ARGUMENT,
    MethodNotFoundError: code_pb2.NOT_FOUND,
    InvalidParamsError: code_pb2.INVALID_ARGUMENT,
    InternalError: code_pb2.INTERNAL,
    TaskNotFoundError: code_pb2.NOT_FOUND,
    TaskNotCancelableError: code_pb2.FAILED_PRECONDITION,
    PushNotificationNotSupportedError: code_pb2.UNIMPLEMENTED,
    UnsupportedOperationError: code_pb2.UNIMPLEMENTED,
    ContentTypeNotSupportedError: code_pb2.INVALID_ARGUMENT,
    InvalidAgentResponseError: code_pb2.INTERNAL,
}


def get_metadata_value(context: slim_bindings.Context, key: str) -> str:
    """Extract metadata value from slim_bindings context."""
    return context.metadata().get(key, "")


class CallContextBuilder(ABC):
    """A class for building ServerCallContexts using the slim_bindings Context."""

    @abstractmethod
    def build(self, context: slim_bindings.Context) -> ServerCallContext:
        """Builds a ServerCallContext from a SlimRPC Request."""


class DefaultCallContextBuilder(CallContextBuilder):
    """A default implementation of CallContextBuilder."""

    def build(self, context: slim_bindings.Context) -> ServerCallContext:
        """Builds the ServerCallContext."""
        user = UnauthenticatedUser()
        state = {"slim_context": context}
        return ServerCallContext(
            user=user,
            state=state,
            requested_extensions=get_requested_extensions(
                [get_metadata_value(context, HTTP_EXTENSION_HEADER)],
            ),
        )


class SRPCCompatHandler(a2a_pb2_slimrpc.A2AServiceServicer):
    """Backward compatible SlimRPC handler for A2A v0.3."""

    def __init__(
        self,
        agent_card: AgentCard,
        request_handler: RequestHandler,
        context_builder: CallContextBuilder | None = None,
        card_modifier: Callable[[AgentCard], AgentCard] | None = None,
    ) -> None:
        """Initializes the SRPCCompatHandler.

        Args:
            agent_card: The AgentCard describing the agent's capabilities (v1.0 proto).
            request_handler: The underlying v1.0 RequestHandler instance.
            context_builder: The CallContextBuilder object.
            card_modifier: An optional callback to modify the agent card.
        """
        self.agent_card = agent_card
        self.handler03 = RequestHandler03(request_handler=request_handler)
        self.context_builder = context_builder or DefaultCallContextBuilder()
        self.card_modifier = card_modifier

    async def raise_error_response(self, error: A2AError) -> None:
        """Raises SlimRPC errors appropriately."""
        code = _SLIM_ERROR_CODE_MAP.get(type(error), code_pb2.UNKNOWN)
        raise SlimRPCError(
            code=code,
            message=f"{type(error).__name__}: {error.message}",
            details=None,
        )

    async def SendMessage(
        self,
        request: a2a_v0_3_pb2.SendMessageRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.SendMessageResponse:
        """Handles the 'SendMessage' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.SendMessageRequest(
                id=0, params=proto_utils.FromProto.message_send_params(request)
            )
            result = await self.handler03.on_message_send(req_v03, server_context)
            if isinstance(result, types_v03.Task):
                return a2a_v0_3_pb2.SendMessageResponse(
                    task=proto_utils.ToProto.task(result)
                )
            return a2a_v0_3_pb2.SendMessageResponse(
                msg=proto_utils.ToProto.message(result)
            )
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.SendMessageResponse()

    async def SendStreamingMessage(
        self,
        request: a2a_v0_3_pb2.SendMessageRequest,
        context: slim_bindings.Context,
    ) -> AsyncIterable[a2a_v0_3_pb2.StreamResponse]:
        """Handles the 'SendStreamingMessage' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.SendMessageRequest(
                id=0, params=proto_utils.FromProto.message_send_params(request)
            )
            async for v03_stream_resp in self.handler03.on_message_send_stream(
                req_v03, server_context
            ):
                yield proto_utils.ToProto.stream_response(v03_stream_resp.result)
        except A2AError as e:
            await self.raise_error_response(e)

    async def GetTask(
        self,
        request: a2a_v0_3_pb2.GetTaskRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.Task:
        """Handles the 'GetTask' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.GetTaskRequest(
                id=0, params=proto_utils.FromProto.task_query_params(request)
            )
            task = await self.handler03.on_get_task(req_v03, server_context)
            return proto_utils.ToProto.task(task)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.Task()

    async def CancelTask(
        self,
        request: a2a_v0_3_pb2.CancelTaskRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.Task:
        """Handles the 'CancelTask' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.CancelTaskRequest(
                id=0, params=proto_utils.FromProto.task_id_params(request)
            )
            task = await self.handler03.on_cancel_task(req_v03, server_context)
            return proto_utils.ToProto.task(task)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.Task()

    async def TaskSubscription(
        self,
        request: a2a_v0_3_pb2.TaskSubscriptionRequest,
        context: slim_bindings.Context,
    ) -> AsyncIterable[a2a_v0_3_pb2.StreamResponse]:
        """Handles the 'TaskSubscription' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.TaskResubscriptionRequest(
                id=0, params=proto_utils.FromProto.task_id_params(request)
            )
            async for v03_stream_resp in self.handler03.on_subscribe_to_task(
                req_v03, server_context
            ):
                yield proto_utils.ToProto.stream_response(v03_stream_resp.result)
        except A2AError as e:
            await self.raise_error_response(e)

    async def CreateTaskPushNotificationConfig(
        self,
        request: a2a_v0_3_pb2.CreateTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.TaskPushNotificationConfig:
        """Handles the 'CreateTaskPushNotificationConfig' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            req_v03 = types_v03.SetTaskPushNotificationConfigRequest(
                id=0,
                params=proto_utils.FromProto.task_push_notification_config_request(
                    request
                ),
            )
            res_v03 = await self.handler03.on_create_task_push_notification_config(
                req_v03, server_context
            )
            return proto_utils.ToProto.task_push_notification_config(res_v03)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.TaskPushNotificationConfig()

    async def GetTaskPushNotificationConfig(
        self,
        request: a2a_v0_3_pb2.GetTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.TaskPushNotificationConfig:
        """Handles the 'GetTaskPushNotificationConfig' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            task_id, config_id = _extract_task_and_config_id(request.name)
            req_v03 = types_v03.GetTaskPushNotificationConfigRequest(
                id=0,
                params=types_v03.GetTaskPushNotificationConfigParams(
                    id=task_id, push_notification_config_id=config_id
                ),
            )
            res_v03 = await self.handler03.on_get_task_push_notification_config(
                req_v03, server_context
            )
            return proto_utils.ToProto.task_push_notification_config(res_v03)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.TaskPushNotificationConfig()

    async def ListTaskPushNotificationConfig(
        self,
        request: a2a_v0_3_pb2.ListTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.ListTaskPushNotificationConfigResponse:
        """Handles the 'ListTaskPushNotificationConfig' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            task_id = _extract_task_id(request.parent)
            req_v03 = types_v03.ListTaskPushNotificationConfigRequest(
                id=0,
                params=types_v03.ListTaskPushNotificationConfigParams(id=task_id),
            )
            res_v03 = await self.handler03.on_list_task_push_notification_configs(
                req_v03, server_context
            )
            return a2a_v0_3_pb2.ListTaskPushNotificationConfigResponse(
                configs=[
                    proto_utils.ToProto.task_push_notification_config(c)
                    for c in res_v03
                ]
            )
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_v0_3_pb2.ListTaskPushNotificationConfigResponse()

    async def GetAgentCard(
        self,
        request: a2a_v0_3_pb2.GetAgentCardRequest,
        context: slim_bindings.Context,
    ) -> a2a_v0_3_pb2.AgentCard:
        """Get the agent card for the agent served (v0.3)."""
        card_to_serve = self.agent_card
        if self.card_modifier:
            card_to_serve = self.card_modifier(card_to_serve)
        return proto_utils.ToProto.agent_card(
            conversions.to_compat_agent_card(card_to_serve)
        )

    async def DeleteTaskPushNotificationConfig(
        self,
        request: a2a_v0_3_pb2.DeleteTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> empty_pb2.Empty:
        """Handles the 'DeleteTaskPushNotificationConfig' SlimRPC method (v0.3)."""
        try:
            server_context = self.context_builder.build(context)
            task_id, config_id = _extract_task_and_config_id(request.name)
            req_v03 = types_v03.DeleteTaskPushNotificationConfigRequest(
                id=0,
                params=types_v03.DeleteTaskPushNotificationConfigParams(
                    id=task_id, push_notification_config_id=config_id
                ),
            )
            await self.handler03.on_delete_task_push_notification_config(
                req_v03, server_context
            )
            return empty_pb2.Empty()
        except A2AError as e:
            await self.raise_error_response(e)
        return empty_pb2.Empty()


def _extract_task_id(resource_name: str) -> str:
    """Extracts task_id from resource name like 'tasks/{id}'."""
    m = proto_utils.TASK_NAME_MATCH.match(resource_name)
    if not m:
        raise InvalidParamsError(message=f"No task for {resource_name}")
    return m.group(1)


def _extract_task_and_config_id(resource_name: str) -> tuple[str, str]:
    """Extracts task_id and config_id from resource name."""
    m = proto_utils.TASK_PUSH_CONFIG_NAME_MATCH.match(resource_name)
    if not m:
        raise InvalidParamsError(message=f"Bad resource name {resource_name}")
    return m.group(1), m.group(2)
