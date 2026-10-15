# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""End-to-end: JWT (EdDSA / Ed25519) identities over an in-process SLIM node.

An agent bootstrapped through ``connect_and_subscribe`` with a JWT identity
serves an A2A ``SendMessage`` from a client whose token is signed by the
trusted key, the handler sees that client's verified ``sub`` / ``iss``, and
a caller whose token is signed by an untrusted key is rejected.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
import slim_bindings
from a2a.auth.user import User
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Role,
    SendMessageRequest,
)

from slima2a import (
    SlimIdentity,
    SlimUser,
    connect_and_subscribe,
    initialize_slim_service,
)
from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import (
    A2AServiceStub,
    add_A2AServiceServicer_to_server,
)

serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")

ENDPOINT = "127.0.0.1:46413"
SLIM_URL = f"http://{ENDPOINT}"
ISSUER = "slim-a2a-python-test"
AUDIENCE = ["agntcy/demo"]
AGENT = "jwt_echo_agent"
HOUR = timedelta(hours=1)


def _keypair() -> tuple[str, str]:
    key = ed25519.Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


# One Ed25519 key pair is the trust root of this test mesh.
TRUSTED_PRIVATE, TRUSTED_PUBLIC = _keypair()


# The generated stubs don't declare enum variants (``JWT``, ``DATA``, ...) as
# subclasses of their enum, hence the ``arg-type`` ignores; at runtime they are.


def _key(pem: str) -> slim_bindings.JwtKeyConfig:
    return slim_bindings.JwtKeyConfig(
        algorithm=slim_bindings.JwtAlgorithm.ED_DSA,
        format=slim_bindings.JwtKeyFormat.PEM,
        key=slim_bindings.JwtKeyData.DATA(value=pem),  # type: ignore[arg-type]
    )


def jwt_identity(subject: str, signing_key: str = TRUSTED_PRIVATE) -> SlimIdentity:
    """Signs with ``signing_key``; trusts only tokens from the trusted key."""
    return SlimIdentity(
        provider=slim_bindings.IdentityProviderConfig.JWT(  # type: ignore[arg-type]
            config=slim_bindings.ClientJwtAuth(
                key=slim_bindings.JwtKeyType.ENCODING(key=_key(signing_key)),  # type: ignore[arg-type]
                audience=AUDIENCE,
                issuer=ISSUER,
                subject=subject,
                duration=HOUR,
            )
        ),
        verifier=slim_bindings.IdentityVerifierConfig.JWT(  # type: ignore[arg-type]
            config=slim_bindings.JwtAuth(
                key=slim_bindings.JwtKeyType.DECODING(key=_key(TRUSTED_PUBLIC)),  # type: ignore[arg-type]
                audience=AUDIENCE,
                issuer=ISSUER,
                subject=None,
                duration=HOUR,
            )
        ),
    )


class EchoExecutor(AgentExecutor):
    """Echoes the input; records the caller the handler saw."""

    def __init__(self) -> None:
        self.users: list[User] = []

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self.users.append(context.call_context.user)
        await event_queue.enqueue_event(
            new_text_message(
                context.get_user_input(),
                context_id=context.context_id,
                task_id=context.task_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


AGENT_CARD = AgentCard(
    name="JWT Echo Agent",
    description="Echo agent authenticated with a JWT identity.",
    supported_interfaces=[
        AgentInterface(url=f"agntcy/demo/{AGENT}", protocol_binding="slimrpc")
    ],
    version="1.0.0",
    default_input_modes=["text"],
    default_output_modes=["text"],
    capabilities=AgentCapabilities(streaming=False),
)


def _request(text: str) -> SendMessageRequest:
    message = new_text_message(text, role=Role.ROLE_USER)
    message.message_id = str(uuid.uuid4())
    return SendMessageRequest(message=message)


class Mesh:
    """An in-process SLIM node with a JWT-identified echo agent."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def start(self) -> None:
        self.service = await initialize_slim_service(log_level="error")
        await self.service.run_server_async(
            slim_bindings.new_insecure_server_config(ENDPOINT)
        )
        await asyncio.sleep(0.3)

        server_name = slim_bindings.Name("agntcy", "demo", AGENT)
        app, self.conn_id = await connect_and_subscribe(
            self.service,
            server_name,
            slim_url=SLIM_URL,
            identity=jwt_identity(f"agntcy/demo/{AGENT}"),
        )
        self.executor = EchoExecutor()
        handler = SRPCHandler(
            AGENT_CARD,
            DefaultRequestHandler(
                agent_executor=self.executor,
                task_store=InMemoryTaskStore(),
                agent_card=AGENT_CARD,
            ),
        )
        self.server = slim_bindings.Server.new_with_connection(
            app, server_name, self.conn_id
        )
        add_A2AServiceServicer_to_server(handler, self.server)
        self.serve_task = self.loop.create_task(self.server.serve_async())
        await asyncio.sleep(0.3)

    async def stub(self, name: str, signing_key: str) -> A2AServiceStub:
        # The global service holds one connection per node endpoint, so the
        # in-process client apps reuse the agent's connection.
        local_name = slim_bindings.Name("agntcy", "demo", name)
        identity = jwt_identity(f"agntcy/demo/{name}", signing_key)
        app = self.service.create_app(local_name, identity.provider, identity.verifier)
        await app.subscribe_async(local_name, self.conn_id)
        await asyncio.sleep(0.3)
        channel = slim_bindings.Channel.new_with_connection(
            app, slim_bindings.Name("agntcy", "demo", AGENT), self.conn_id
        )
        return A2AServiceStub(channel)

    async def stop(self) -> None:
        with contextlib.suppress(Exception):  # ignore shutdown races
            await self.server.shutdown_async()
        self.serve_task.cancel()


@pytest.fixture(scope="module")
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    # Let background A2A/slimrpc tasks finish cancelling before closing.
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()


@pytest.fixture(scope="module")
def mesh(loop: asyncio.AbstractEventLoop) -> Iterator[Mesh]:
    mesh = Mesh(loop)
    loop.run_until_complete(mesh.start())
    yield mesh
    loop.run_until_complete(mesh.stop())


def test_accepts_caller_with_trusted_jwt(
    loop: asyncio.AbstractEventLoop, mesh: Mesh
) -> None:
    async def scenario() -> str:
        stub = await mesh.stub("jwt_client", TRUSTED_PRIVATE)
        response = await stub.SendMessage(
            _request("hello with jwt"), timeout=timedelta(seconds=10)
        )
        return response.message.parts[0].text

    assert loop.run_until_complete(scenario()) == "hello with jwt"
    # The handler sees the subject and issuer verified from the caller's token.
    assert mesh.executor.users[-1] == SlimUser("agntcy/demo/jwt_client", ISSUER)
    assert mesh.executor.users[-1].is_authenticated


def test_rejects_caller_with_untrusted_jwt(
    loop: asyncio.AbstractEventLoop, mesh: Mesh
) -> None:
    rogue_private, _ = _keypair()

    async def scenario() -> None:
        stub = await mesh.stub("jwt_rogue", rogue_private)
        await stub.SendMessage(_request("x"), timeout=timedelta(seconds=3))

    # The agent drops the rogue caller's session setup ("identity
    # verification failed: token invalid"), so the call never completes.
    with pytest.raises(slim_bindings.RpcError) as excinfo:
        loop.run_until_complete(asyncio.wait_for(scenario(), timeout=15))
    assert excinfo.value.code in (  # type: ignore[attr-defined]
        slim_bindings.RpcCode.DEADLINE_EXCEEDED,
        slim_bindings.RpcCode.UNAUTHENTICATED,
        slim_bindings.RpcCode.PERMISSION_DENIED,
    )
