# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""Helper utilities for initializing and configuring SLIM bindings."""

import asyncio
from typing import Literal

import slim_bindings


async def initialize_slim_service(
    log_level: Literal["trace", "debug", "info", "warn", "error"] = "info",
) -> slim_bindings.Service:
    """Initialize SLIM service with default configuration.

    This function sets up the event loop and initializes the SLIM service
    with default tracing, runtime, and service configurations.

    Args:
        log_level: The log level for SLIM tracing. Defaults to "info".

    Returns:
        The initialized SLIM Service instance.

    Example:
        >>> service = await initialize_slim_service(log_level="debug")
    """
    # Set the event loop for slim_bindings to handle callbacks from Rust threads
    slim_bindings.uniffi_set_event_loop(asyncio.get_running_loop())  # type: ignore[arg-type]

    # Initialize slim_bindings service
    tracing_config = slim_bindings.new_tracing_config()
    runtime_config = slim_bindings.new_runtime_config()
    service_config = slim_bindings.new_service_config()

    tracing_config.log_level = log_level

    slim_bindings.initialize_with_configs(
        tracing_config=tracing_config,
        runtime_config=runtime_config,
        service_config=[service_config],
    )

    return slim_bindings.get_global_service()


async def connect_and_subscribe(
    service: slim_bindings.Service,
    local_name: slim_bindings.Name,
    slim_url: str = "http://localhost:46357",
    secret: str = "secretsecretsecretsecretsecretsecret",
) -> tuple[slim_bindings.App, int]:
    """Connect to SLIM server and subscribe to a local name.

    Args:
        service: The SLIM Service instance.
        local_name: The local name to subscribe to.
        slim_url: The SLIM server URL. Defaults to "http://localhost:46357".
        secret: The shared secret for app creation. Defaults to a placeholder value.

    Returns:
        A tuple of (local_app, connection_id).

    Example:
        >>> service = await initialize_slim_service()
        >>> local_name = slim_bindings.Name("agntcy", "demo", "my_agent")
        >>> local_app, conn_id = await connect_and_subscribe(service, local_name)
    """
    # Connect to SLIM
    client_config = slim_bindings.new_insecure_client_config(slim_url)
    conn_id = await service.connect_async(client_config)

    # Create app with shared secret
    local_app = service.create_app_with_secret(local_name, secret)

    # Subscribe to local name
    await local_app.subscribe_async(local_name, conn_id)

    return local_app, conn_id


async def setup_slim_client(
    namespace: str,
    group: str,
    name: str,
    slim_url: str = "http://localhost:46357",
    secret: str = "secretsecretsecretsecretsecretsecret",
    log_level: Literal["trace", "debug", "info", "warn", "error"] = "info",
) -> tuple[slim_bindings.Service, slim_bindings.App, slim_bindings.Name, int]:
    """Complete SLIM client setup in one call.

    This is a convenience function that combines initialize_slim_service and
    connect_and_subscribe.

    Args:
        namespace: The namespace for the SLIM name (e.g., "agntcy").
        group: The group for the SLIM name (e.g., "demo").
        name: The name component (e.g., "my_agent" or "client").
        slim_url: The SLIM server URL. Defaults to "http://localhost:46357".
        secret: The shared secret for app creation. Defaults to a placeholder value.
        log_level: The log level for SLIM tracing. Defaults to "info".

    Returns:
        A tuple of (service, local_app, local_name, connection_id).

    Example:
        >>> service, local_app, local_name, conn_id = await setup_slim_client(
        ...     "agntcy", "demo", "my_agent"
        ... )
    """
    service = await initialize_slim_service(log_level=log_level)
    local_name = slim_bindings.Name(namespace, group, name)
    local_app, conn_id = await connect_and_subscribe(
        service, local_name, slim_url, secret
    )

    return service, local_app, local_name, conn_id
