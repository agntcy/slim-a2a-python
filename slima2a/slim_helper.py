# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""Helper utilities for initializing and configuring SLIM bindings."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import slim_bindings

DEFAULT_SLIM_URL = "http://localhost:46357"
"""Default SLIM node URL, used over a plaintext connection when neither
``slim_url`` nor ``client_config`` is given."""


@dataclass(frozen=True)
class SlimIdentity:
    """A SLIM app identity, passed to ``Service.create_app``.

    ``provider`` is how this app proves who it is to others; ``verifier`` is
    how it verifies the identity of its peers. Any provider/verifier supported
    by ``slim_bindings`` works: shared secret, static or signed JWT (including
    EdDSA), JWT verification with PEM/JWK/JWKS keys, or SPIRE.
    """

    provider: slim_bindings.IdentityProviderConfig
    verifier: slim_bindings.IdentityVerifierConfig


_AppFactory = Callable[[slim_bindings.Service, slim_bindings.Name], slim_bindings.App]


def _resolve_connect_options(
    slim_url: str | None,
    client_config: slim_bindings.ClientConfig | None,
    secret: str | None,
    identity: SlimIdentity | None,
) -> tuple[slim_bindings.ClientConfig, _AppFactory]:
    """Validate the connection/identity options.

    Raises before any connection is opened when the options conflict or no
    credential was supplied. Returns the client config to dial and a factory
    that creates the app with the selected identity.
    """
    if slim_url is not None and client_config is not None:
        raise ValueError(
            "pass either `slim_url` or `client_config`, not both "
            "(`client_config.endpoint` sets the node URL)."
        )
    if secret is not None and identity is not None:
        raise ValueError("pass either `secret` or `identity`, not both.")

    create_app: _AppFactory
    if identity is not None:
        if not isinstance(identity, SlimIdentity):
            raise TypeError(
                "`identity` must be a SlimIdentity(provider=..., verifier=...)."
            )

        def create_app(
            service: slim_bindings.Service, name: slim_bindings.Name
        ) -> slim_bindings.App:
            return service.create_app(name, identity.provider, identity.verifier)

    elif secret:

        def create_app(
            service: slim_bindings.Service, name: slim_bindings.Name
        ) -> slim_bindings.App:
            return service.create_app_with_secret(name, secret)

    else:
        raise ValueError(
            "a SLIM credential is required: pass `secret` (shared secret, "
            ">= 32 chars) or `identity` (SlimIdentity(provider, verifier)). "
            "There is no default secret."
        )

    if client_config is None:
        client_config = slim_bindings.new_insecure_client_config(
            slim_url if slim_url is not None else DEFAULT_SLIM_URL
        )
    return client_config, create_app


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
    slim_url: str | None = None,
    secret: str | None = None,
    *,
    identity: SlimIdentity | None = None,
    client_config: slim_bindings.ClientConfig | None = None,
) -> tuple[slim_bindings.App, int]:
    """Connect to a SLIM node and subscribe to a local name.

    Exactly one of ``secret`` or ``identity`` is required; there is no default
    credential. At most one of ``slim_url`` or ``client_config`` may be given.

    Args:
        service: The SLIM Service instance.
        local_name: The local name to subscribe to.
        slim_url: SLIM node URL for a plaintext, unauthenticated connection.
            Defaults to ``DEFAULT_SLIM_URL`` when ``client_config`` is not set.
        secret: Shared secret for app creation (>= 32 chars). Mutually
            exclusive with ``identity``.
        identity: Identity provider/verifier for app creation, passed to
            ``Service.create_app``. Mutually exclusive with ``secret``.
        client_config: Full ``slim_bindings.ClientConfig`` for the node
            connection (TLS, bearer/JWT/basic auth, headers, timeouts), e.g.
            from ``slim_bindings.new_secure_client_config``. Replaces
            ``slim_url``.

    Returns:
        A tuple of (local_app, connection_id).

    Raises:
        ValueError: if no credential is given, or if conflicting options are
            passed. Raised before any connection is opened.

    Example:
        >>> service = await initialize_slim_service()
        >>> local_name = slim_bindings.Name("agntcy", "demo", "my_agent")
        >>> local_app, conn_id = await connect_and_subscribe(
        ...     service, local_name, secret=os.environ["SLIM_SHARED_SECRET"]
        ... )
    """
    resolved_config, create_app = _resolve_connect_options(
        slim_url, client_config, secret, identity
    )

    conn_id = await service.connect_async(resolved_config)
    local_app = create_app(service, local_name)

    # Subscribe to local name
    await local_app.subscribe_async(local_name, conn_id)

    return local_app, conn_id


async def setup_slim_client(
    namespace: str,
    group: str,
    name: str,
    slim_url: str | None = None,
    secret: str | None = None,
    log_level: Literal["trace", "debug", "info", "warn", "error"] = "info",
    *,
    identity: SlimIdentity | None = None,
    client_config: slim_bindings.ClientConfig | None = None,
) -> tuple[slim_bindings.Service, slim_bindings.App, slim_bindings.Name, int]:
    """Complete SLIM client setup in one call.

    This is a convenience function that combines initialize_slim_service and
    connect_and_subscribe. The connection and identity options are the same
    as for :func:`connect_and_subscribe`: exactly one of ``secret`` or
    ``identity``, and at most one of ``slim_url`` or ``client_config``.

    Args:
        namespace: The namespace for the SLIM name (e.g., "agntcy").
        group: The group for the SLIM name (e.g., "demo").
        name: The name component (e.g., "my_agent" or "client").
        slim_url: SLIM node URL for a plaintext connection. Defaults to
            ``DEFAULT_SLIM_URL`` when ``client_config`` is not set.
        secret: Shared secret for app creation (>= 32 chars).
        log_level: The log level for SLIM tracing. Defaults to "info".
        identity: Identity provider/verifier for app creation.
        client_config: Full client config for the node connection.

    Returns:
        A tuple of (service, local_app, local_name, connection_id).

    Raises:
        ValueError: if no credential is given, or if conflicting options are
            passed. Raised before the SLIM service is initialized.

    Example:
        >>> service, local_app, local_name, conn_id = await setup_slim_client(
        ...     "agntcy", "demo", "my_agent", secret=os.environ["SLIM_SHARED_SECRET"]
        ... )
    """
    # Validate before touching the global service so misconfiguration fails fast.
    _resolve_connect_options(slim_url, client_config, secret, identity)

    service = await initialize_slim_service(log_level=log_level)
    local_name = slim_bindings.Name(namespace, group, name)
    local_app, conn_id = await connect_and_subscribe(
        service,
        local_name,
        slim_url,
        secret,
        identity=identity,
        client_config=client_config,
    )

    return service, local_app, local_name, conn_id
