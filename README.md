# SLIMA2A

[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/agntcy/slim-a2a-python/badge)](https://scorecard.dev/viewer/?uri=github.com/agntcy/slim-a2a-python)

SLIMA2A is a SLIM transport for A2A using slim's RPC protocol (srpc). It allows
agents to communicate over the SLIM network using the A2A protocol, using SLIM
identities for authentication and addressing.

## Requirements

- `slim-bindings` 3.3.x (3.3.4 or later)
- `a2a-sdk` 1.1.x

Both A2A protocol versions are supported: v1.0 (`slima2a.types.v1`, the default)
and v0.3 (`slima2a.types.v0`, via the compatibility layer in `slima2a.compat.v3_0`).

## Compile the protobuf

- Refer to this [documentation](https://docs.agntcy.org/slim/slim-slimrpc-compiler/) to download the slimrpc compiler for your system (`agntcy-protoc-slimrpc-plugin` 3.x, matching `slim-bindings` 3.x) and make sure to have it in $PATH.
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
import os

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
    secret=os.environ["SLIM_SHARED_SECRET"],  # or identity=..., see below
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
import os

import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

# Set the event loop for slim_bindings. Call the top-level wrapper: slimrpc
# lives in its own UniFFI namespace and the loop has to be registered on both,
# which the wrapper takes care of.
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

# Create app with a shared secret (>= 32 chars), or use
# service.create_app(local_name, provider, verifier) for a real identity
local_app = service.create_app_with_secret(
    local_name, os.environ["SLIM_SHARED_SECRET"]
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
import os

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
    secret=os.environ["SLIM_SHARED_SECRET"],  # or identity=..., see below
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
import os

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

# Set the event loop for slim_bindings. Call the top-level wrapper: slimrpc
# lives in its own UniFFI namespace and the loop has to be registered on both,
# which the wrapper takes care of.
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

# Create app with a shared secret (>= 32 chars), or use
# service.create_app(local_name, provider, verifier) for a real identity
slim_local_app = service.create_app_with_secret(
    local_name, os.environ["SLIM_SHARED_SECRET"]
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

## Identity and node connection

`setup_slim_client` and `connect_and_subscribe` configure two independent things:

- **App identity** (required, exactly one): `secret`, a shared secret (>= 32
  chars), or `identity=SlimIdentity(provider, verifier)`, any
  `IdentityProviderConfig` / `IdentityVerifierConfig` the bindings support
  (shared secret, static or signed JWT including EdDSA, JWT verification with
  PEM/JWK/JWKS keys, SPIRE). It is passed to `Service.create_app`. There is
  **no default secret**: omitting both raises `ValueError`.
- **Node connection** (optional, at most one): `slim_url` for a plaintext
  connection (default `http://localhost:46357`), or `client_config`, a full
  `slim_bindings.ClientConfig` with TLS, auth, headers and timeouts.

Conflicting pairs (`secret` + `identity`, `slim_url` + `client_config`) raise
`ValueError` before any connection is opened.

With a shared secret, anyone who holds the secret can claim any SLIM name. A
per-agent JWT identity binds each app to a key you control. Every member of a
session needs a compatible identity type. Here an agent signs its own Ed25519
JWT, trusts tokens verified against a JWKS file, and connects to a node over
TLS with a bearer token:

```python
from datetime import timedelta

import slim_bindings

from slima2a import SlimIdentity, setup_slim_client

name = "agntcy/demo/my_agent"
hour = timedelta(hours=1)

identity = SlimIdentity(
    provider=slim_bindings.IdentityProviderConfig.JWT(
        config=slim_bindings.ClientJwtAuth(
            key=slim_bindings.JwtKeyType.ENCODING(
                key=slim_bindings.JwtKeyConfig(
                    algorithm=slim_bindings.JwtAlgorithm.ED_DSA,
                    format=slim_bindings.JwtKeyFormat.PEM,
                    key=slim_bindings.JwtKeyData.FILE(path="/etc/slim/agent-key.pem"),
                )
            ),
            audience=["agntcy/demo"],
            issuer="agntcy",
            subject=name,
            duration=hour,
        )
    ),
    verifier=slim_bindings.IdentityVerifierConfig.JWT(
        config=slim_bindings.JwtAuth(
            # A JWKS file of trusted public keys acts as the allowlist.
            key=slim_bindings.JwtKeyType.DECODING(
                key=slim_bindings.JwtKeyConfig(
                    algorithm=slim_bindings.JwtAlgorithm.ED_DSA,
                    format=slim_bindings.JwtKeyFormat.JWKS,
                    key=slim_bindings.JwtKeyData.FILE(path="/etc/slim/trusted.jwks.json"),
                )
            ),
            audience=["agntcy/demo"],
            issuer="agntcy",
            subject=None,
            duration=hour,
        )
    ),
)

# TLS (system CA pool) plus a bearer token read from a file.
client_config = slim_bindings.new_secure_client_config("https://slim.example.com:443")
client_config.auth = slim_bindings.ClientAuthenticationConfig.STATIC_JWT(
    config=slim_bindings.StaticJwtAuth(
        token_file="/var/run/secrets/slim/token", duration=hour
    )
)

service, local_app, local_name, conn_id = await setup_slim_client(
    "agntcy", "demo", "my_agent", identity=identity, client_config=client_config
)
```

[`tests/test_identity_e2e.py`](tests/test_identity_e2e.py) runs the same
identity setup end to end with an in-memory key.

### Caller identity on the server

SLIM verifies the caller's identity before a request reaches the handler.
`DefaultCallContextBuilder` (in both `SRPCHandler` and `SRPCCompatHandler`)
hands it to the handler as a `slima2a.SlimUser`, built from the slimrpc
`Context.peer_subject()` and `peer_issuer()`: the `sub` and `iss` of the token
the caller's app set up the MLS session with, as checked by your verifier.
When the session carries no verified subject, the caller is
`UnauthenticatedUser`. In a group session the subject is the MLS sender of the
request. Caller-supplied metadata is never used as identity.

Read it in an `AgentExecutor` (or anywhere the `ServerCallContext` is
available):

```python
from slima2a import SlimUser


class MyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user = context.call_context.user
        if not isinstance(user, SlimUser):
            raise PermissionError("unauthenticated caller")
        print(user.subject, user.issuer)  # e.g. "agntcy/demo/client", "my-issuer"
```

`user.user_name` is the subject. The raw slimrpc `Context` stays available as
`call_context.state["slim_context"]`. For a different policy, pass your own
`CallContextBuilder` as `context_builder`.

## Helper Functions

The `slima2a` package provides convenient helper functions to simplify SLIM setup:

- **`setup_slim_client(namespace, group, name, slim_url=None, secret=None, log_level="info", *, identity=None, client_config=None)`** - Complete SLIM client setup in one call
- **`initialize_slim_service(log_level="info")`** - Initialize SLIM service with default configuration
- **`connect_and_subscribe(service, local_name, slim_url=None, secret=None, *, identity=None, client_config=None)`** - Connect to SLIM server and subscribe to a local name

Both require exactly one of `secret` or `identity`; see
[Identity and node connection](#identity-and-node-connection).

## Examples

Runnable end-to-end examples live under [`examples/`](examples):

- [`examples/echo_agent`](examples/echo_agent) - minimal echo agent, covering unary,
  streaming, A2A v0.3 compatibility and multicast
- [`examples/travel_planner_agent`](examples/travel_planner_agent) - a LangChain-based agent

They expect a SLIM node reachable at `http://localhost:46357`, and use the
shared secret from `$SLIM_SHARED_SECRET` (or `--secret` for the echo agent),
falling back to a publicly known demo-only placeholder that the sibling
slim-a2a SDK examples share.
