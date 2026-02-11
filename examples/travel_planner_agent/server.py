import asyncio
import logging

# Disable a2a telemetry debugging completely
logging.getLogger("a2a.utils.telemetry").setLevel(logging.ERROR)  # type: ignore
logging.getLogger("asyncio").setLevel(logging.ERROR)  # type: ignore

# ruff: noqa: E402
import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

from examples.travel_planner_agent.agent_executor import TravelPlannerAgentExecutor
from slima2a.handler import SRPCHandler
from slima2a.types.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server


async def main() -> None:
    # Set the event loop for slim_bindings to handle callbacks from Rust threads
    slim_bindings.slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

    skill = AgentSkill(
        id="travel_planner",
        name="travel planner agent",
        description="travel planner",
        tags=["travel planner"],
        examples=["hello", "nice to meet you!"],
    )

    agent_card = AgentCard(
        name="travel planner Agent",
        description="travel planner",
        url="http://localhost:10001/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=TravelPlannerAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    servicer = SRPCHandler(agent_card, request_handler)

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
    local_name = slim_bindings.Name("agntcy", "demo", "travel_planner_agent")

    # Connect to SLIM
    client_config = slim_bindings.new_insecure_client_config("http://localhost:46357")
    conn_id = await service.connect_async(client_config)

    # Create app with shared secret
    local_app = service.create_app_with_secret(local_name, "secret")

    # Subscribe to local name
    await local_app.subscribe_async(local_name, conn_id)

    # Create server
    server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

    add_A2AServiceServicer_to_server(
        servicer,
        server,
    )

    # Run server
    logging.getLogger(__name__).info("Server starting...")
    await server.serve_async()


if __name__ == "__main__":
    asyncio.run(main())
