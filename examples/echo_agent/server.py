import argparse
import asyncio
import logging

import slim_bindings
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

from examples.echo_agent.echo_agent_executor import EchoAgentExecutor
from slima2a.handler import SRPCHandler
from slima2a.types.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server


async def main() -> None:
    args = parse_arguments()

    logging.basicConfig(level=args.log_level)

    # Set the event loop for slim_bindings to handle callbacks from Rust threads
    slim_bindings.slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

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
        url="http://localhost:9999/",
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

    servicer: SRPCHandler | A2AStarletteApplication
    match args.type:
        case "slimrpc":
            servicer = SRPCHandler(agent_card, default_request_handler)

            # Initialize slim_bindings service
            tracing_config = slim_bindings.new_tracing_config()
            runtime_config = slim_bindings.new_runtime_config()
            service_config = slim_bindings.new_service_config()

            tracing_config.log_level = "info"

            slim_bindings.initialize_with_configs(
                tracing_config=tracing_config,
                runtime_config=runtime_config,
                service_config=[service_config],
            )

            service = slim_bindings.get_global_service()

            # Create local name
            local_name = slim_bindings.Name("agntcy", "demo", "echo_agent")

            # Connect to SLIM
            client_config = slim_bindings.new_insecure_client_config(
                "http://localhost:46357"
            )
            conn_id = await service.connect_async(client_config)

            # Create app with shared secret
            local_app = service.create_app_with_secret(
                local_name, "secretsecretsecretsecretsecretsecret"
            )

            # Subscribe to local name
            await local_app.subscribe_async(local_name, conn_id)

            # Create server
            server = slim_bindings.Server.new_with_connection(
                local_app, local_name, conn_id
            )

            add_A2AServiceServicer_to_server(
                servicer,
                server,
            )

            # Run server
            logging.getLogger(__name__).info("Server starting...")
            await server.serve_async()
        case "starlette":
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

    args = parser.parse_args()

    if args.type not in ["slimrpc", "starlette"]:
        raise ValueError(f"Invalid server type: {args.type}")

    return args


if __name__ == "__main__":
    asyncio.run(main())
