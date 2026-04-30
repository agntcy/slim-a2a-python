import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import httpx
from a2a.client import (
    A2ACardResolver,
    Client,
    create_text_message_object,
    minimal_agent_card,
)
from a2a.types.a2a_pb2 import AgentCard, SendMessageRequest
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
)

from slima2a import setup_slim_client
from slima2a.client_transport import (
    ClientConfig,
    MulticastClient,
    SRPCClientFactory,
    slimrpc_channel_factory,
    slimrpc_group_channel_factory,
)

BASE_URL = "http://localhost:9999"

logger = logging.getLogger(__name__)


async def fetch_agent_card(resolver: A2ACardResolver) -> AgentCard:
    agent_card = None

    try:
        logger.info(f"fetching agent card from: {BASE_URL}{AGENT_CARD_WELL_KNOWN_PATH}")
        agent_card = await resolver.get_agent_card()
        logger.info(f"fetched agent card: {agent_card}")

    except Exception as e:
        logger.error(f"failed fetching public agent card: {e}", exc_info=True)
        raise RuntimeError("failed fetching public agent card") from e

    return agent_card


async def main() -> None:
    args = parse_arguments()

    logging.basicConfig(level=args.log_level)

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
        streaming=args.stream,
        httpx_client=httpx_client,
        slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
        slimrpc_group_channel_factory=slimrpc_group_channel_factory(
            slim_local_app, conn_id
        ),
    )
    client_factory = SRPCClientFactory(client_config)

    if args.a2a_version == "v0":
        from slima2a.compat.v3_0.client_transport import SRPCCompatTransport

        client_factory.register("slimrpc", SRPCCompatTransport.create)  # type: ignore

    agent_names = [f"agntcy/demo/{name.strip()}" for name in args.agents.split(",")]

    match args.type:
        case "slimrpc":
            agent_card = minimal_agent_card(",".join(agent_names), ["slimrpc"])
        case "starlette":
            agent_card = await fetch_agent_card(
                resolver=A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=BASE_URL,
                )
            )
        case _:
            raise ValueError(f"Invalid client type: {args.type}")

    client = client_factory.create(card=agent_card)

    if isinstance(client, MulticastClient):
        print(f"> {args.text} (multicast to {agent_names})")
        await send_message_multicast(client, args.text)
    else:
        logger.info("A2AClient initialized.")
        response_text = await send_message(client, args.text)
        print(f"> {args.text}")
        print(response_text)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--log-level",
        type=str,
        required=False,
        default="ERROR",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        required=False,
        default=False,
    )
    parser.add_argument(
        "--text",
        type=str,
        required=True,
    )
    parser.add_argument(
        "--type",
        type=str,
        required=False,
        default="slimrpc",
    )
    parser.add_argument(
        "--a2a-version",
        type=str,
        required=False,
        default="v1",
        choices=["v0", "v1"],
    )
    parser.add_argument(
        "--agents",
        type=str,
        required=False,
        default="echo_agent",
        help="Comma-separated agent names (e.g. echo_agent_1,echo_agent_2). Multiple names triggers multicast.",
    )

    args = parser.parse_args()

    if args.type not in ["slimrpc", "starlette"]:
        raise ValueError(f"Invalid client type: {args.type}")

    return args


async def send_message(
    client: Client,
    text: str,
) -> str:
    message = create_text_message_object(content=text)
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
                if task:
                    logger.info(f"task ({task.id}) status: {task.status.state}")
                    if task.artifacts:
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
        logger.error(
            f"failed sending message or processing response: {e}",
            exc_info=True,
        )
        raise RuntimeError("failed sending message or processing response") from e

    return output


async def send_message_multicast(
    client: MulticastClient,
    text: str,
) -> None:
    message = create_text_message_object(content=text)
    request = SendMessageRequest(message=message)

    try:
        async for source, response in client.send_message(request):
            output = ""
            which = response.WhichOneof("payload")
            if which == "message":
                for part in response.message.parts:
                    if part.WhichOneof("content") == "text":
                        output += part.text
            elif which == "task":
                if response.task.artifacts:
                    for artifact in response.task.artifacts:
                        for part in artifact.parts:
                            if part.WhichOneof("content") == "text":
                                output += part.text
            elif which == "artifact_update":
                artifact = response.artifact_update.artifact
                for part in artifact.parts:
                    if part.WhichOneof("content") == "text":
                        output += part.text
            if output:
                print(f"  [{source}] {output}")
    except Exception as e:
        logger.error(
            f"failed sending multicast message: {e}",
            exc_info=True,
        )
        raise RuntimeError("failed sending multicast message") from e


if __name__ == "__main__":
    asyncio.run(main())
