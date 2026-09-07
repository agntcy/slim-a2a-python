# SLIMA2A

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/agntcy/slim-a2a-python/badge)](https://scorecard.dev/viewer/?uri=github.com/agntcy/slim-a2a-python)

SLIMA2A is a SLIM transport for A2A using slim's RPC protocol (srpc). It allows
agents to communicate over the SLIM network using the A2A protocol, using SLIM
identities for authentication and addressing.

## Requirements

- `slim-bindings` 2.x
- `a2a-sdk` 1.1.x

Both A2A protocol versions are supported: v1.0 (`slima2a.types.v1`, the default)
and v0.3 (`slima2a.types.v0`, via the compatibility layer in `slima2a.compat.v3_0`).

## Compile the protobuf

- Refer to this [documentation](https://docs.agntcy.org/slim/slim-slimrpc-compiler/) to download the correct slirpc compiler for your system (2.x, matching `slim-bindings` 2.x) and make sure to have in in $PATH.
- Install [bufbuild](https://buf.build/docs/cli/installation/)

Run the following from the repo root:

```sh
task generate
```

This regenerates both the A2A v0.3 (`slima2a/types/v0`) and v1.0 (`slima2a/types/v1`)
SlimRPC bindings. Use `task generate-v0` / `task generate-v1` to regenerate one of them.

## Server usage

### Quick Start (Recommended)

```python
import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from slima2a import setup_slim_client
from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

# Initialize and connect to SLIM (simplified helper)
service, local_app, local_name, conn_id = await setup_slim_client(
    namespace="agntcy",
    group="demo",
    name="echo_agent",
)

# Create request handler
agent_executor = MyAgentExecutor()
task_store = InMemoryTaskStore()
request_handler = DefaultRequestHandler(
    agent_executor=agent_executor,
    task_store=task_store,
    agent_card=agent_card,
)

# Create servicer
servicer = SRPCHandler(agent_card, request_handler)

# Create server
server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

add_A2AServiceServicer_to_server(servicer, server)

# Run server
await server.serve_async()
```

`agent_card` is an `a2a.types.a2a_pb2.AgentCard` (the v1.0 protobuf message), and
the agent is reachable on the SLIM network under `agntcy/demo/echo_agent` — the
namespace/group/name triple passed to `setup_slim_client`.

### Advanced Setup (Manual Configuration)

If you need more control over the SLIM configuration:

```python
import asyncio

import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

# Set the event loop for slim_bindings. Call the top-level wrapper: as of
# slim-bindings 2.0 slimrpc lives in its own UniFFI namespace and the loop has
# to be registered on both, which the wrapper takes care of.
slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

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
client_config = slim_bindings.new_insecure_client_config("http://localhost:46357")
conn_id = await service.connect_async(client_config)

# Create app with shared secret
local_app = service.create_app_with_secret(
    local_name, "secretsecretsecretsecretsecretsecret"
)

# Subscribe to local name
await local_app.subscribe_async(local_name, conn_id)

# Create request handler
agent_executor = MyAgentExecutor()
task_store = InMemoryTaskStore()
request_handler = DefaultRequestHandler(
    agent_executor=agent_executor,
    task_store=task_store,
    agent_card=agent_card,
)

# Create servicer
servicer = SRPCHandler(agent_card, request_handler)

# Create server
server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

add_A2AServiceServicer_to_server(servicer, server)

# Run server
await server.serve_async()
```

### Serving A2A v0.3 clients

`SRPCCompatHandler` exposes the same `DefaultRequestHandler` over the A2A v0.3
service definition. Register both servicers on one server to accept v0.3 and v1.0
clients simultaneously:

```python
from slima2a.compat.v3_0.handler import SRPCCompatHandler
from slima2a.handler import SRPCHandler
from slima2a.types.v0.a2a_pb2_slimrpc import (
    add_A2AServiceServicer_to_server as add_v0,
)
from slima2a.types.v1.a2a_pb2_slimrpc import (
    add_A2AServiceServicer_to_server as add_v1,
)

server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

add_v0(SRPCCompatHandler(agent_card, request_handler), server)
add_v1(SRPCHandler(agent_card, request_handler), server)

await server.serve_async()
```

Note that `SRPCCompatHandler` takes the **v1.0** agent card and request handler —
it converts to and from the v0.3 wire types internally.

## Client Usage

### Quick Start (Recommended)

```python
import httpx
from a2a.client import minimal_agent_card
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest

from slima2a import setup_slim_client
from slima2a.client_transport import (
    ClientConfig,
    MultiAgentClientFactory,
    slimrpc_channel_factory,
)

# Initialize and connect to SLIM (simplified helper)
service, slim_local_app, local_name, conn_id = await setup_slim_client(
    namespace="agntcy",
    group="demo",
    name="client",
)

# Create client config
httpx_client = httpx.AsyncClient()
client_config = ClientConfig(
    supported_protocol_bindings=["slimrpc"],
    streaming=True,
    httpx_client=httpx_client,
    slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
)

# Create client factory (the "slimrpc" transport is registered automatically)
client_factory = MultiAgentClientFactory(client_config)

# Create client with minimal agent card
agent_card = minimal_agent_card("agntcy/demo/echo_agent", ["slimrpc"])
client = client_factory.create(card=agent_card)

# Send message
request = SendMessageRequest(message=new_text_message("Hello, world!", role=Role.ROLE_USER))

async for stream_response in client.send_message(request=request):
    match stream_response.WhichOneof("payload"):
        case "message":
            parts = stream_response.message.parts
        case "task":
            parts = [p for a in stream_response.task.artifacts for p in a.parts]
        case "artifact_update":
            parts = stream_response.artifact_update.artifact.parts
        case _:
            parts = []
    for part in parts:
        if part.WhichOneof("content") == "text":
            print(part.text)
```

`client.send_message()` yields `StreamResponse` messages whose `payload` oneof is
one of `message`, `task` or `artifact_update` — which one you get depends on the
agent, so handle all three. See [`examples/echo_agent/client.py`](examples/echo_agent/client.py)
for a fuller version.

### Advanced Setup (Manual Configuration)

If you need more control over the SLIM configuration:

```python
import asyncio

import httpx
import slim_bindings
from a2a.client import minimal_agent_card
from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest

from slima2a.client_transport import (
    ClientConfig,
    MultiAgentClientFactory,
    slimrpc_channel_factory,
)

# Set the event loop for slim_bindings. Call the top-level wrapper: as of
# slim-bindings 2.0 slimrpc lives in its own UniFFI namespace and the loop has
# to be registered on both, which the wrapper takes care of.
slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

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
local_name = slim_bindings.Name("agntcy", "demo", "client")

# Connect to SLIM
client_config_slim = slim_bindings.new_insecure_client_config("http://localhost:46357")
conn_id = await service.connect_async(client_config_slim)

# Create app with shared secret
slim_local_app = service.create_app_with_secret(
    local_name, "secretsecretsecretsecretsecretsecret"
)

# Subscribe to local name
await slim_local_app.subscribe_async(local_name, conn_id)

# Create client config
httpx_client = httpx.AsyncClient()
client_config = ClientConfig(
    supported_protocol_bindings=["slimrpc"],
    streaming=True,
    httpx_client=httpx_client,
    slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
)

# Create client factory (the "slimrpc" transport is registered automatically)
client_factory = MultiAgentClientFactory(client_config)

# Create client with minimal agent card
agent_card = minimal_agent_card("agntcy/demo/echo_agent", ["slimrpc"])
client = client_factory.create(card=agent_card)

# Send message
request = SendMessageRequest(message=new_text_message("Hello, world!", role=Role.ROLE_USER))

async for stream_response in client.send_message(request=request):
    match stream_response.WhichOneof("payload"):
        case "message":
            parts = stream_response.message.parts
        case "task":
            parts = [p for a in stream_response.task.artifacts for p in a.parts]
        case "artifact_update":
            parts = stream_response.artifact_update.artifact.parts
        case _:
            parts = []
    for part in parts:
        if part.WhichOneof("content") == "text":
            print(part.text)
```

### Talking to an A2A v0.3 agent

Override the registered `slimrpc` transport with the v0.3 compatibility transport:

```python
from slima2a.compat.v3_0.client_transport import SRPCCompatTransport

client_factory = MultiAgentClientFactory(client_config)
client_factory.register("slimrpc", SRPCCompatTransport.create, multiagent=True)
```

### Multicast (querying several agents at once)

Passing a list of agent cards to `MultiAgentClientFactory.create()` returns a
`MulticastClient` that sends a single request to every agent in the group and
yields `(source, response)` tuples as the replies arrive. This requires
`slimrpc_group_channel_factory` on the config:

```python
from slima2a.client_transport import (
    ClientConfig,
    MultiAgentClientFactory,
    slimrpc_channel_factory,
    slimrpc_group_channel_factory,
)

client_config = ClientConfig(
    supported_protocol_bindings=["slimrpc"],
    streaming=True,
    httpx_client=httpx_client,
    slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
    slimrpc_group_channel_factory=slimrpc_group_channel_factory(
        slim_local_app, conn_id
    ),
)

client_factory = MultiAgentClientFactory(client_config)
client = client_factory.create(
    card=[
        minimal_agent_card("agntcy/demo/echo_agent_1", ["slimrpc"]),
        minimal_agent_card("agntcy/demo/echo_agent_2", ["slimrpc"]),
    ]
)

async for source, stream_response in client.send_message(request):
    print(source, stream_response.WhichOneof("payload"))
```

`source` is a `RpcMessageContext` identifying the agent that produced the response,
so replies from different agents can be told apart as they interleave.

## Helper Functions

The `slima2a` package provides convenient helper functions to simplify SLIM setup:

- **`setup_slim_client(namespace, group, name, slim_url="http://localhost:46357", secret="...", log_level="info")`** - Complete SLIM client setup in one call
- **`initialize_slim_service(log_level="info")`** - Initialize SLIM service with default configuration
- **`connect_and_subscribe(service, local_name, slim_url="http://localhost:46357", secret="...")`** - Connect to SLIM server and subscribe to a local name

## Examples

Runnable end-to-end examples live under [`examples/`](examples):

- [`examples/echo_agent`](examples/echo_agent) - minimal echo agent, covering unary,
  streaming, A2A v0.3 compatibility and multicast
- [`examples/travel_planner_agent`](examples/travel_planner_agent) - a LangChain-based agent

They expect a SLIM node reachable at `http://localhost:46357`.
