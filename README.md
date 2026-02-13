# SLIMA2A

SLIMA2A is a SLIM transport for A2A using slim's RPC protocol (srpc). It allows
agents to communicate over the SLIM network using the A2A protocol, using SLIM
identities for authentication and addressing.

## Compile the protobuf

 - Refer to this [documentation](xxx) to download the correct slirpc compiler for your system and make sure to have in in $PATH.
 - Install [bufbuild](https://buf.build/docs/cli/installation/)

Run the following from the repo root:

```sh
buf generate
```

## Server usage

### Quick Start (Recommended)

```/dev/null/server_example.py
import asyncio
import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from slima2a import setup_slim_client
from slima2a.handler import SRPCHandler
from slima2a.types.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

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
)

# Create servicer
servicer = SRPCHandler(agent_card, request_handler)

# Create server
server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

add_A2AServiceServicer_to_server(servicer, server)

# Run server
await server.serve_async()
```

### Advanced Setup (Manual Configuration)

If you need more control over the SLIM configuration:

```/dev/null/server_advanced_example.py
import asyncio
import slim_bindings
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from slima2a.handler import SRPCHandler
from slima2a.types.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

# Set the event loop for slim_bindings
slim_bindings.slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

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
)

# Create servicer
servicer = SRPCHandler(agent_card, request_handler)

# Create server
server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)

add_A2AServiceServicer_to_server(servicer, server)

# Run server
await server.serve_async()
```

## Client Usage

### Quick Start (Recommended)

```/dev/null/client_example.py
import asyncio
import httpx
from a2a.client import ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, TextPart
from slima2a import setup_slim_client
from slima2a.client_transport import ClientConfig, SRPCTransport, slimrpc_channel_factory

# Initialize and connect to SLIM (simplified helper)
service, slim_local_app, local_name, conn_id = await setup_slim_client(
    namespace="agntcy",
    group="demo",
    name="client",
)

# Create client config
httpx_client = httpx.AsyncClient()
client_config = ClientConfig(
    supported_transports=["JSONRPC", "slimrpc"],
    streaming=True,
    httpx_client=httpx_client,
    slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
)

# Create client factory and register transport
client_factory = ClientFactory(client_config)
client_factory.register("slimrpc", SRPCTransport.create)

# Create client with minimal agent card
agent_card = minimal_agent_card("agntcy/demo/echo_agent", ["slimrpc"])
client = client_factory.create(card=agent_card)

# Send message
request = Message(
    role=Role.user,
    message_id="request-id",
    parts=[Part(root=TextPart(text="Hello, world!"))],
)

async for event in client.send_message(request=request):
    if isinstance(event, Message):
        for part in event.parts:
            if isinstance(part.root, TextPart):
                print(part.root.text)
```

### Advanced Setup (Manual Configuration)

If you need more control over the SLIM configuration:

```/dev/null/client_advanced_example.py
import asyncio
import httpx
import slim_bindings
from a2a.client import ClientFactory, minimal_agent_card
from a2a.types import Message, Part, Role, TextPart
from slima2a.client_transport import ClientConfig, SRPCTransport, slimrpc_channel_factory

# Set the event loop for slim_bindings
slim_bindings.slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())

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
    supported_transports=["JSONRPC", "slimrpc"],
    streaming=True,
    httpx_client=httpx_client,
    slimrpc_channel_factory=slimrpc_channel_factory(slim_local_app, conn_id),
)

# Create client factory and register transport
client_factory = ClientFactory(client_config)
client_factory.register("slimrpc", SRPCTransport.create)

# Create client with minimal agent card
agent_card = minimal_agent_card("agntcy/demo/echo_agent", ["slimrpc"])
client = client_factory.create(card=agent_card)

# Send message
request = Message(
    role=Role.user,
    message_id="request-id",
    parts=[Part(root=TextPart(text="Hello, world!"))],
)

async for event in client.send_message(request=request):
    if isinstance(event, Message):
        for part in event.parts:
            if isinstance(part.root, TextPart):
                print(part.root.text)
```

## Helper Functions

The `slima2a` package provides convenient helper functions to simplify SLIM setup:

- **`setup_slim_client(namespace, group, name, slim_url="http://localhost:46357", secret="...", log_level="info")`** - Complete SLIM client setup in one call
- **`initialize_slim_service(log_level="info")`** - Initialize SLIM service with default configuration
- **`connect_and_subscribe(service, local_name, slim_url="http://localhost:46357", secret="...")`** - Connect to SLIM server and subscribe to a local name
```
