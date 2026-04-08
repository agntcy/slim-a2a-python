import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from examples.echo_agent.echo_agent_executor import EchoAgentExecutor
from slima2a import setup_slim_client


async def main() -> None:
    args = parse_arguments()

    logging.basicConfig(level=args.log_level)

    skill = AgentSkill(
        id="echo",
        name="echo",
        description="returns the received prompt",
        tags=["echo"],
        examples=["hi", "hello", "how are you"],
    )

    agent_card = AgentCard(
        name="Echo Agent",
        description="Just a simple echo agent that returns the received prompt",
        supported_interfaces=[
            AgentInterface(url="http://localhost:9999/", protocol_binding="JSONRPC")
        ],
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    agent_executor = EchoAgentExecutor()
    task_store = InMemoryTaskStore()
    default_request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=task_store,
    )

    match args.type:
        case "slimrpc":
            # Initialize and connect to SLIM
            service, local_app, local_name, conn_id = await setup_slim_client(
                namespace="agntcy",
                group="demo",
                name="echo_agent",
                secret="my_shared_secret_for_testing_purposes_only",
            )

            # Create server
            server = slim_bindings.Server.new_with_connection(
                local_app, local_name, conn_id
            )

            if args.a2a_version in ("v0", "both"):
                from slima2a.compat.v3_0.handler import SRPCCompatHandler
                from slima2a.types.v0.a2a_pb2_slimrpc import (
                    add_A2AServiceServicer_to_server as add_v0,
                )

                compat_handler = SRPCCompatHandler(agent_card, default_request_handler)
                add_v0(compat_handler, server)

            if args.a2a_version in ("v1", "both"):
                from slima2a.handler import SRPCHandler
                from slima2a.types.v1.a2a_pb2_slimrpc import (
                    add_A2AServiceServicer_to_server as add_v1,
                )

                handler = SRPCHandler(agent_card, default_request_handler)
                add_v1(handler, server)

            # Run server
            await server.serve_async()
        case "starlette":
            import uvicorn
            from a2a.server.apps import A2AStarletteApplication

            servicer = A2AStarletteApplication(
                agent_card=agent_card,
                http_handler=default_request_handler,
            )

            uvicorn.run(servicer.build(), host="0.0.0.0", port=9999)
        case _:
            raise ValueError(f"Invalid server type: {args.type}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--type", type=str, required=False, default="slimrpc")

    parser.add_argument(
        "--log-level",
        type=str,
        required=False,
        default="ERROR",
    )

    parser.add_argument(
        "--a2a-version",
        type=str,
        required=False,
        default="v1",
        choices=["v0", "v1", "both"],
    )

    args = parser.parse_args()

    if args.type not in ["slimrpc", "starlette"]:
        raise ValueError(f"Invalid server type: {args.type}")

    return args


if __name__ == "__main__":
    asyncio.run(main())
