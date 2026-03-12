import asyncio
import logging
from uuid import uuid4

# Disable a2a telemetry debugging before any a2a imports
logging.getLogger("a2a.utils.telemetry").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.ERROR)

# ruff: noqa: E402
from typing import cast

import httpx
from a2a.client import Client, ClientFactory, minimal_agent_card
from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
)

from slima2a import setup_slim_client
from slima2a.client_transport import (
    ClientConfig,
    SRPCTransport,
    slimrpc_channel_factory,
)

# Two travel planner instances to multicast to
AGENT_NAMES = [
    "agntcy/demo/travel_planner_agent1",
    "agntcy/demo/travel_planner_agent2",
]

logger = logging.getLogger(__name__)


def print_welcome_message() -> None:
    print("Welcome to the generic A2A client!")
    print("Please enter your query (type 'exit' to quit):")


def get_user_query() -> str:
    return input("\n> ")


async def interact_with_server(client: Client) -> None:
    while True:
        user_input = get_user_query()
        if user_input.lower() == "exit":
            print("bye!~")
            break

        request_id = str(uuid4())
        request = Message(
            role=Role.user,
            message_id=request_id,
            parts=[Part(root=TextPart(text=user_input))],
        )

        # Group output by task_id so responses from each server are kept separate.
        outputs: dict[str, str] = {}
        try:
            async for response in client.send_message(request=request):
                if isinstance(response, Message):
                    outputs.setdefault("msg", "")
                    for part in response.parts:
                        if isinstance(part.root, TextPart):
                            outputs["msg"] += part.root.text
                else:
                    _, update = response

                    if isinstance(update, TaskArtifactUpdateEvent):
                        outputs.setdefault(update.task_id, "")
                        for part in update.artifact.parts:
                            if isinstance(part.root, TextPart):
                                outputs[update.task_id] += part.root.text

        except Exception as e:
            raise RuntimeError("failed sending message or processing response") from e

        for i, text in enumerate(outputs.values()):
            if i > 0:
                print("\n---")
            print(text, end="", flush=True)
        await asyncio.sleep(0.1)


async def main() -> None:
    print_welcome_message()

    httpx_client = httpx.AsyncClient()

    # Initialize and connect to SLIM
    service, slim_local_app, local_name, conn_id = await setup_slim_client(
        namespace="agntcy",
        group="demo",
        name="client",
    )

    client_config = ClientConfig(
        supported_transports=["JSONRPC", "slimrpc"],
        streaming=True,
        httpx_client=httpx_client,
        slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
    )
    client_factory = ClientFactory(client_config)

    # mypy: the register API expects a different callable type; safe to ignore here.
    client_factory.register("slimrpc", SRPCTransport.create)  # type: ignore

    client = client_factory.create(
        card=minimal_agent_card(",".join(AGENT_NAMES), ["slimrpc"])
    )

    # Fetch agent cards from all servers in the group.
    transport = cast(SRPCTransport, client._transport)  # type: ignore[attr-defined]
    async for card in transport.get_all_cards():
        logger.info(f"agent card: {card.model_dump_json(indent=2, exclude_none=True)}")

    # Fetch the real card from the first server so that
    # client._card.capabilities.streaming=True before send_message.
    await client.get_card()

    await interact_with_server(client)


if __name__ == "__main__":
    asyncio.run(main())
