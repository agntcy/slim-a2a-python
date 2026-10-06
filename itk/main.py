# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""The slima2a agent the A2A Integration Test Kit runs as the code under test.

The ITK launcher starts it as `uv run --locked main.py --httpPort N --grpcPort M`
and waits for `GET http://127.0.0.1:N/.well-known/agent-card.json` to answer.

One executor and one task store sit behind up to four bindings:

- `SLIMRPC` over the SLIM node at `$SLIM_ENDPOINT`, the binding under test.
  Served only when that variable is set, which the ITK does for a slimrpc
  run after starting the node.
- `GRPC` on `--grpcPort`, the binding slimrpc carries the same service as.
- `JSONRPC` at `/jsonrpc/` and `HTTP+JSON` at `/rest` on `--httpPort`.

Serving them from one agent is the point: a conformance run over SLIM and one
over gRPC exercise the same executor and request handler, so any difference
in results is the transport's.

The SLIM name is derived from the HTTP port, so concurrent agents on one node
never collide and the launcher needs no SLIM-specific arguments.
"""

import argparse
import asyncio
import contextlib
import logging
import os

import grpc
import httpx
import slim_bindings
import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler, GrpcHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
    create_rest_routes,
)
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import a2a_pb2_grpc
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette
from starlette.routing import BaseRoute
from tck_executor import TckAgentExecutor

from slima2a import setup_slim_client
from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

logger = logging.getLogger("slima2a-itk")

#: Where the SLIM node listens. The ITK starts one for a slimrpc run and
#: exports this; unset, the agent serves no slimrpc interface at all.
SLIM_ENDPOINT = os.environ.get("SLIM_ENDPOINT")

#: Shared secret for the SLIM app. Must match the ITK client's.
SLIM_SHARED_SECRET = os.environ.get(
    "SLIM_SHARED_SECRET", "secretsecretsecretsecretsecretsecret"
)

#: The SLIM namespace and group every ITK agent registers under.
SLIM_NAMESPACE = "agntcy"
SLIM_GROUP = "itk"

#: The protocol_binding value slima2a clients look for on a card.
SLIMRPC_BINDING = "slimrpc"


def slim_name(http_port: int) -> tuple[str, str, str]:
    return SLIM_NAMESPACE, SLIM_GROUP, f"agent-{http_port}"


def build_card(http_port: int, grpc_port: int, *, slim: bool) -> AgentCard:
    """The card advertises exactly the bindings this process serves."""
    http_root = f"http://127.0.0.1:{http_port}"
    interfaces = (
        [
            AgentInterface(
                url="/".join(slim_name(http_port)),
                protocol_binding=SLIMRPC_BINDING,
                protocol_version="1.0",
            )
        ]
        if slim
        else []
    )
    return AgentCard(
        name="slima2a ITK agent",
        description="ACTS system under test for slima2a, the SLIM transport for A2A.",
        version="0.1.0",
        supported_interfaces=[
            *interfaces,
            AgentInterface(
                url=f"127.0.0.1:{grpc_port}",
                protocol_binding="GRPC",
                protocol_version="1.0",
            ),
            AgentInterface(
                url=f"{http_root}/jsonrpc/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
            AgentInterface(
                url=f"{http_root}/rest",
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
            ),
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
        skills=[
            AgentSkill(
                id="tck",
                name="ACTS behaviors",
                description="Responds to the tck-* prefixes the ACTS corpus sends.",
                tags=["acts", "tck"],
            )
        ],
    )


async def connect_slim(
    card: AgentCard, handler: DefaultRequestHandler, http_port: int, endpoint: str
) -> slim_bindings.Server:
    """Register on the SLIM node and mount the A2A service there.

    Awaited before anything else listens: if the node is unreachable the
    agent exits, which the launcher reports as a failed start instead of an
    agent that looks healthy and answers on every binding but SLIM.
    """
    _, local_app, local_name, conn_id = await setup_slim_client(
        *slim_name(http_port),
        slim_url=endpoint,
        secret=SLIM_SHARED_SECRET,
        log_level="warn",
    )
    server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)
    add_A2AServiceServicer_to_server(SRPCHandler(card, handler), server)
    logger.info(
        "slimrpc serving as %s via %s", "/".join(slim_name(http_port)), endpoint
    )
    return server


async def start_grpc(handler: DefaultRequestHandler, grpc_port: int) -> grpc.aio.Server:
    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(GrpcHandler(handler), server)
    server.add_insecure_port(f"127.0.0.1:{grpc_port}")
    await server.start()
    logger.info("gRPC serving on :%d", grpc_port)
    return server


async def main() -> None:
    args = parse_arguments()
    logging.basicConfig(level=args.log_level)

    card = build_card(args.http_port, args.grpc_port, slim=SLIM_ENDPOINT is not None)
    push_store = InMemoryPushNotificationConfigStore()
    handler = DefaultRequestHandler(
        agent_executor=TckAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(httpx.AsyncClient(), push_store),
    )

    serving: set[asyncio.Task] = set()
    if SLIM_ENDPOINT is not None:
        slim_server = await connect_slim(card, handler, args.http_port, SLIM_ENDPOINT)
        serving.add(asyncio.create_task(slim_server.serve_async()))
    else:
        logger.info("SLIM_ENDPOINT unset: not serving slimrpc")
    grpc_server = await start_grpc(handler, args.grpc_port)

    routes: list[BaseRoute] = [*create_agent_card_routes(agent_card=card)]
    routes += create_jsonrpc_routes(request_handler=handler, rpc_url="/jsonrpc/")
    routes += create_rest_routes(request_handler=handler, path_prefix="/rest")
    http = uvicorn.Server(
        uvicorn.Config(
            Starlette(routes=routes),
            host="127.0.0.1",
            port=args.http_port,
            log_level="warning",
        )
    )

    # The card goes up last: it is the launcher's readiness signal, so it only
    # answers once every other binding is already serving.
    serving.add(asyncio.create_task(http.serve()))
    try:
        done, _ = await asyncio.wait(serving, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        http.should_exit = True
        for task in serving:
            task.cancel()
        await grpc_server.stop(grace=None)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--httpPort", dest="http_port", type=int, required=True)
    parser.add_argument("--grpcPort", dest="grpc_port", type=int, required=True)
    parser.add_argument("--log-level", default=os.environ.get("ITK_LOG_LEVEL", "INFO"))
    return parser.parse_args()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
