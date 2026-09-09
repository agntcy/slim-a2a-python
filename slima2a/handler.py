# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

# ruff: noqa: N802
import asyncio
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
from a2a.server.request_handlers.request_handler import RequestHandler, validate
from a2a.types import a2a_pb2
from a2a.types.a2a_pb2 import AgentCard
from a2a.utils import proto_utils
from a2a.utils.errors import A2AError, TaskNotFoundError
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

    @validate(
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

    @validate(
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

    async def SendLiveMessage(
        self,
        request_stream: slim_bindings.RequestStream,
        context: slim_bindings.Context,
        sink: slim_bindings.ResponseSink,
    ) -> AsyncIterable[a2a_pb2.StreamResponse]:
        """Handles the 'SendLiveMessage' SlimRPC bidi streaming method."""
        server_context = self.context_builder.build(context)

        async def _decoded_stream() -> AsyncIterable[a2a_pb2.StreamRequest]:
            while True:
                msg = await request_stream.next_async()
                if msg.is_end():
                    break
                if msg.is_error():
                    raise msg[0]
                if msg.is_data():
                    req = a2a_pb2.StreamRequest.FromString(msg[0])
                    if not server_context.tenant:
                        server_context.tenant = req.tenant
                    yield req

        try:
            async for event in self.request_handler.on_live_message_send(
                _decoded_stream(), server_context
            ):
                yield event
        except A2AError as e:
            await self.raise_error_response(e)

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


class SRPCSharedHandler(a2a_pb2_slimrpc.A2AServiceSharedServicer):
    """Maps incoming broadcast-live SlimRPC SendLiveMessage calls to the request handler.

    Peer agent StreamResponse events are translated to StreamRequest items and
    merged into the unified inbound stream before on_live_message_send is called,
    so application code sees a single mixed stream of client and peer messages.
    """

    def __init__(
        self,
        agent_card: AgentCard,
        request_handler: RequestHandler,
        context_builder: CallContextBuilder | None = None,
        card_modifier: Callable[[AgentCard], AgentCard] | None = None,
    ) -> None:
        self.agent_card = agent_card
        self.request_handler = request_handler
        self.context_builder = context_builder or DefaultCallContextBuilder()
        self.card_modifier = card_modifier

    async def raise_error_response(self, error: A2AError) -> None:
        code = _SLIM_ERROR_CODE_MAP.get(type(error), code_pb2.UNKNOWN)
        raise slim_bindings.RpcError.Rpc(
            code=code,
            message=f"{type(error).__name__}: {error.message}",
            details=None,
        )

    async def SendLiveMessage(
        self,
        request_stream: AsyncIterable[a2a_pb2.StreamRequest],
        context: slim_bindings.Context,
        sink: slim_bindings.ResponseSink,
        peer_responses: AsyncIterable,
    ) -> AsyncIterable[a2a_pb2.StreamResponse]:
        """Handles broadcast SendLiveMessage: merges client stream with translated peer events."""
        server_context = self.context_builder.build(context)

        queue: asyncio.Queue[a2a_pb2.StreamRequest | None] = asyncio.Queue()

        async def _feed_client() -> None:
            try:
                async for req in request_stream:
                    if not server_context.tenant:
                        server_context.tenant = req.tenant
                    await queue.put(req)
            finally:
                await queue.put(None)

        async def _feed_peers() -> None:
            try:
                async for source, stream_response in peer_responses:
                    src_str = str(source)
                    translated = _translate_peer_response(src_str, stream_response)
                    if translated is not None:
                        await queue.put(translated)
            finally:
                await queue.put(None)

        async def _merged_stream() -> AsyncIterable[a2a_pb2.StreamRequest]:
            client_task = asyncio.ensure_future(_feed_client())
            peer_task = asyncio.ensure_future(_feed_peers())
            pending = 2
            try:
                while pending > 0:
                    item = await queue.get()
                    if item is None:
                        pending -= 1
                    else:
                        yield item
            finally:
                client_task.cancel()
                peer_task.cancel()

        try:
            async for event in self.request_handler.on_live_message_send(
                _merged_stream(), server_context
            ):
                yield event
        except A2AError as e:
            await self.raise_error_response(e)


def _translate_peer_response(
    source: str,
    response: a2a_pb2.StreamResponse,
) -> a2a_pb2.StreamRequest | None:
    """Translate a peer StreamResponse to a StreamRequest per spec Section 5."""
    which = response.WhichOneof("payload")
    meta = {"slim-src": source}

    if which == "task":
        task = response.task
        meta["slim-peer-task-id"] = task.id
        msg = a2a_pb2.Message(
            role=a2a_pb2.Role.ROLE_USER,
            parts=[a2a_pb2.Part(text=f"peer task started: {task.id}")],
        )
        return a2a_pb2.StreamRequest(message=msg, metadata=meta)

    if which == "status_update":
        update = response.status_update
        meta["slim-peer-task-id"] = update.task_id
        if update.status.HasField("message"):
            return a2a_pb2.StreamRequest(message=update.status.message, metadata=meta)
        state_name = a2a_pb2.TaskState.Name(update.status.state)
        meta["slim-peer-state"] = state_name
        msg = a2a_pb2.Message(
            role=a2a_pb2.Role.ROLE_USER,
            parts=[a2a_pb2.Part(text=f"peer task state: {state_name}")],
        )
        return a2a_pb2.StreamRequest(message=msg, metadata=meta)

    if which == "artifact_update":
        update = response.artifact_update
        meta["slim-peer-task-id"] = update.task_id
        return a2a_pb2.StreamRequest(artifact_update=update, metadata=meta)

    if which == "message_update":
        update = response.message_update
        meta["slim-peer-task-id"] = update.task_id
        return a2a_pb2.StreamRequest(message=update.message, metadata=meta)

    return None
