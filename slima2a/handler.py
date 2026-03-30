# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

# ruff: noqa: N802
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Callable

import slim_bindings
from a2a import types
from a2a.auth.user import UnauthenticatedUser
from a2a.extensions.common import (
    HTTP_EXTENSION_HEADER,
    get_requested_extensions,
)
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types import a2a_pb2
from a2a.types.a2a_pb2 import AgentCard
from a2a.utils import proto_utils
from a2a.utils.errors import A2AError, TaskNotFoundError
from a2a.utils.helpers import validate, validate_async_generator
from google.protobuf import empty_pb2
from google.rpc import code_pb2

from slima2a.types.v1 import a2a_pb2_slimrpc

SlimRPCError = slim_bindings.RpcError.Rpc  # type: ignore[attr-defined]

_SLIM_ERROR_CODE_MAP = {
    types.InvalidRequestError: code_pb2.INVALID_ARGUMENT,
    types.MethodNotFoundError: code_pb2.NOT_FOUND,
    types.InvalidParamsError: code_pb2.INVALID_ARGUMENT,
    types.InternalError: code_pb2.INTERNAL,
    types.TaskNotFoundError: code_pb2.NOT_FOUND,
    types.TaskNotCancelableError: code_pb2.FAILED_PRECONDITION,
    types.PushNotificationNotSupportedError: code_pb2.UNIMPLEMENTED,
    types.UnsupportedOperationError: code_pb2.UNIMPLEMENTED,
    types.ContentTypeNotSupportedError: code_pb2.INVALID_ARGUMENT,
    types.InvalidAgentResponseError: code_pb2.INTERNAL,
    types.ExtendedAgentCardNotConfiguredError: code_pb2.FAILED_PRECONDITION,
    types.ExtensionSupportRequiredError: code_pb2.FAILED_PRECONDITION,
    types.VersionNotSupportedError: code_pb2.UNIMPLEMENTED,
}


class CallContextBuilder(ABC):
    """A class for building ServerCallContexts using the slim_bindings Context."""

    @abstractmethod
    def build(self, context: slim_bindings.Context) -> ServerCallContext:
        """Builds a ServerCallContext from a SlimRPC Request."""


def get_metadata_value(context: slim_bindings.Context, key: str) -> str:
    """Extract metadata value from slim_bindings context."""
    return context.metadata().get(key, "")


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


class SRPCHandler(a2a_pb2_slimrpc.A2AServiceServicer):
    """Maps incoming SlimRPC requests to the appropriate request handler method."""

    def __init__(
        self,
        agent_card: AgentCard,
        request_handler: RequestHandler,
        context_builder: CallContextBuilder | None = None,
        card_modifier: Callable[[AgentCard], AgentCard] | None = None,
    ) -> None:
        """Initializes the SRPCHandler.

        Args:
            agent_card: The AgentCard describing the agent's capabilities (v1.0 proto).
            request_handler: The underlying v1.0 RequestHandler instance.
            context_builder: The CallContextBuilder object. If none the
                             DefaultCallContextBuilder is used.
            card_modifier: An optional callback to dynamically modify the agent card.
        """
        self.agent_card = agent_card
        self.request_handler = request_handler
        self.context_builder = context_builder or DefaultCallContextBuilder()
        self.card_modifier = card_modifier

    def _build_call_context(
        self,
        context: slim_bindings.Context,
        request: object,
    ) -> ServerCallContext:
        server_context = self.context_builder.build(context)
        server_context.tenant = getattr(request, "tenant", "")
        return server_context

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
        request: a2a_pb2.SendMessageRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.SendMessageResponse:
        """Handles the 'SendMessage' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            task_or_message = await self.request_handler.on_message_send(
                request, server_context
            )
            if isinstance(task_or_message, a2a_pb2.Task):
                return a2a_pb2.SendMessageResponse(task=task_or_message)
            return a2a_pb2.SendMessageResponse(message=task_or_message)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.SendMessageResponse()

    @validate_async_generator(
        lambda self: self.agent_card.capabilities.streaming,
        "Streaming is not supported by the agent",
    )
    async def SendStreamingMessage(
        self,
        request: a2a_pb2.SendMessageRequest,
        context: slim_bindings.Context,
    ) -> AsyncIterable[a2a_pb2.StreamResponse]:
        """Handles the 'SendStreamingMessage' SlimRPC method."""
        server_context = self._build_call_context(context, request)
        try:
            async for event in self.request_handler.on_message_send_stream(
                request, server_context
            ):
                yield proto_utils.to_stream_response(event)
        except A2AError as e:
            await self.raise_error_response(e)
        return

    async def CancelTask(
        self,
        request: a2a_pb2.CancelTaskRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.Task:
        """Handles the 'CancelTask' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            task = await self.request_handler.on_cancel_task(request, server_context)
            if task:
                return task
            await self.raise_error_response(TaskNotFoundError())
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.Task()

    @validate_async_generator(
        lambda self: self.agent_card.capabilities.streaming,
        "Streaming is not supported by the agent",
    )
    async def SubscribeToTask(
        self,
        request: a2a_pb2.SubscribeToTaskRequest,
        context: slim_bindings.Context,
    ) -> AsyncIterable[a2a_pb2.StreamResponse]:
        """Handles the 'SubscribeToTask' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            async for event in self.request_handler.on_subscribe_to_task(
                request, server_context
            ):
                yield proto_utils.to_stream_response(event)
        except A2AError as e:
            await self.raise_error_response(e)

    async def GetTask(
        self,
        request: a2a_pb2.GetTaskRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.Task:
        """Handles the 'GetTask' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            task = await self.request_handler.on_get_task(request, server_context)
            if task:
                return task
            await self.raise_error_response(TaskNotFoundError())
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.Task()

    async def ListTasks(
        self,
        request: a2a_pb2.ListTasksRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.ListTasksResponse:
        """Handles the 'ListTasks' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            return await self.request_handler.on_list_tasks(request, server_context)
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.ListTasksResponse()

    async def GetTaskPushNotificationConfig(
        self,
        request: a2a_pb2.GetTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.TaskPushNotificationConfig:
        """Handles the 'GetTaskPushNotificationConfig' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            return await self.request_handler.on_get_task_push_notification_config(
                request, server_context
            )
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.TaskPushNotificationConfig()

    @validate(
        lambda self: self.agent_card.capabilities.push_notifications,
        "Push notifications are not supported by the agent",
    )
    async def CreateTaskPushNotificationConfig(
        self,
        request: a2a_pb2.TaskPushNotificationConfig,
        context: slim_bindings.Context,
    ) -> a2a_pb2.TaskPushNotificationConfig:
        """Handles the 'CreateTaskPushNotificationConfig' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            return await self.request_handler.on_create_task_push_notification_config(
                request, server_context
            )
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.TaskPushNotificationConfig()

    async def ListTaskPushNotificationConfigs(
        self,
        request: a2a_pb2.ListTaskPushNotificationConfigsRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.ListTaskPushNotificationConfigsResponse:
        """Handles the 'ListTaskPushNotificationConfigs' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            return await self.request_handler.on_list_task_push_notification_configs(
                request, server_context
            )
        except A2AError as e:
            await self.raise_error_response(e)
        return a2a_pb2.ListTaskPushNotificationConfigsResponse()

    async def DeleteTaskPushNotificationConfig(
        self,
        request: a2a_pb2.DeleteTaskPushNotificationConfigRequest,
        context: slim_bindings.Context,
    ) -> empty_pb2.Empty:
        """Handles the 'DeleteTaskPushNotificationConfig' SlimRPC method."""
        try:
            server_context = self._build_call_context(context, request)
            await self.request_handler.on_delete_task_push_notification_config(
                request, server_context
            )
            return empty_pb2.Empty()
        except A2AError as e:
            await self.raise_error_response(e)
        return empty_pb2.Empty()

    async def GetExtendedAgentCard(
        self,
        request: a2a_pb2.GetExtendedAgentCardRequest,
        context: slim_bindings.Context,
    ) -> a2a_pb2.AgentCard:
        """Get the extended agent card for the agent served."""
        card_to_serve = self.agent_card
        if self.card_modifier:
            card_to_serve = self.card_modifier(card_to_serve)
        return card_to_serve
