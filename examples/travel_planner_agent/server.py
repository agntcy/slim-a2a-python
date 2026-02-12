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
from slima2a import setup_slim_client
from slima2a.handler import SRPCHandler
from slima2a.types.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server


async def main() -> None:
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

    # Initialize and connect to SLIM
    service, local_app, local_name, conn_id = await setup_slim_client(
        namespace="agntcy",
        group="demo",
        name="travel_planner_agent",
    )

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
