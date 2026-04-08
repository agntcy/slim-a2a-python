import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

# Disable a2a telemetry debugging before any a2a imports
logging.getLogger("a2a.utils.telemetry").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.ERROR)

# ruff: noqa: E402
import httpx
from a2a.client import (
    Client,
    ClientFactory,
    create_text_message_object,
    minimal_agent_card,
)
from a2a.types.a2a_pb2 import SendMessageRequest

from slima2a import setup_slim_client
from slima2a.client_transport import (
    ClientConfig,
    SRPCTransport,
    slimrpc_channel_factory,
)


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

        message = create_text_message_object(content=user_input)
        request = SendMessageRequest(message=message)

        output = ""
        try:
            async for stream_response, task in client.send_message(request=request):
                which = stream_response.WhichOneof("payload")
                if which == "message":
                    for part in stream_response.message.parts:
                        if part.WhichOneof("content") == "text":
                            output += part.text
                elif which == "task":
                    if task and task.artifacts:
                        for artifact in task.artifacts:
                            for part in artifact.parts:
                                if part.WhichOneof("content") == "text":
                                    output += part.text
                elif which == "artifact_update":
                    artifact = stream_response.artifact_update.artifact
                    for part in artifact.parts:
                        if part.WhichOneof("content") == "text":
                            output += part.text

        except Exception as e:
            raise RuntimeError("failed sending message or processing response") from e

        print(output, end="", flush=True)
        await asyncio.sleep(0.1)


async def main() -> None:
    print_welcome_message()

    httpx_client = httpx.AsyncClient()

    # Initialize and connect to SLIM
    service, slim_local_app, local_name, conn_id = await setup_slim_client(
        namespace="agntcy",
        group="demo",
        name="client",
        secret="my_shared_secret_for_testing_purposes_only",
    )

    client_config = ClientConfig(
        supported_protocol_bindings=["slimrpc"],
        streaming=True,
        httpx_client=httpx_client,
        slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
    )
    client_factory = ClientFactory(client_config)

    # mypy: the register API expects a different callable type; safe to ignore here.
    client_factory.register("slimrpc", SRPCTransport.create)  # type: ignore
    agent_card = minimal_agent_card("agntcy/demo/travel_planner_agent", ["slimrpc"])
    client = client_factory.create(card=agent_card)

    await interact_with_server(client)


if __name__ == "__main__":
    asyncio.run(main())
