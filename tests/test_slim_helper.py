# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the connection/identity options of the SLIM helpers.

They run against a fake ``Service``, so no SLIM node is needed.
"""

import asyncio
from typing import Any
from unittest import mock

import pytest
import slim_bindings

import slima2a.slim_helper as helper
from slima2a import (
    DEFAULT_SLIM_URL,
    SlimIdentity,
    connect_and_subscribe,
    setup_slim_client,
)

SECRET = "unit-test-secret-unit-test-secret-0123"
NAME = slim_bindings.Name("agntcy", "test", "unit")


class FakeApp:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[slim_bindings.Name, int]] = []

    async def subscribe_async(self, name: slim_bindings.Name, conn_id: int) -> None:
        self.subscriptions.append((name, conn_id))


class FakeService:
    def __init__(self) -> None:
        self.app = FakeApp()
        self.connect_async = mock.AsyncMock(return_value=7)
        self.create_app = mock.Mock(return_value=self.app)
        self.create_app_with_secret = mock.Mock(return_value=self.app)


def run(service: FakeService, **kwargs: Any) -> tuple[Any, int]:  # noqa: ANN401
    return asyncio.run(
        connect_and_subscribe(service, NAME, **kwargs)  # type: ignore[arg-type]
    )


def shared_secret_identity() -> SlimIdentity:
    # The generated stubs don't declare enum variants as subclasses of their
    # enum, hence the type ignores; at runtime they are.
    return SlimIdentity(
        provider=slim_bindings.IdentityProviderConfig.SHARED_SECRET(  # type: ignore[arg-type]
            id="unit", data=SECRET
        ),
        verifier=slim_bindings.IdentityVerifierConfig.SHARED_SECRET(  # type: ignore[arg-type]
            id="unit", data=SECRET
        ),
    )


@pytest.mark.parametrize("secret", [None, ""])
def test_rejects_missing_credential_before_connecting(secret: str | None) -> None:
    service = FakeService()
    with pytest.raises(ValueError, match="credential is required"):
        run(service, secret=secret)
    service.connect_async.assert_not_called()


def test_rejects_secret_and_identity() -> None:
    service = FakeService()
    with pytest.raises(ValueError, match="either `secret` or `identity`"):
        run(service, secret=SECRET, identity=shared_secret_identity())
    service.connect_async.assert_not_called()


def test_rejects_slim_url_and_client_config() -> None:
    service = FakeService()
    with pytest.raises(ValueError, match="either `slim_url` or `client_config`"):
        run(
            service,
            secret=SECRET,
            slim_url="http://localhost:1",
            client_config=slim_bindings.new_insecure_client_config(
                "http://localhost:2"
            ),
        )
    service.connect_async.assert_not_called()


def test_rejects_identity_of_wrong_type() -> None:
    service = FakeService()
    with pytest.raises(TypeError, match="SlimIdentity"):
        run(service, identity=("provider", "verifier"))


def test_secret_uses_default_url_and_create_app_with_secret() -> None:
    service = FakeService()
    app, conn_id = run(service, secret=SECRET)

    assert app is service.app
    assert conn_id == 7
    (config,), _ = service.connect_async.call_args
    assert config.endpoint == DEFAULT_SLIM_URL
    service.create_app_with_secret.assert_called_once_with(NAME, SECRET)
    service.create_app.assert_not_called()
    assert service.app.subscriptions == [(NAME, 7)]


def test_secret_with_slim_url_positional() -> None:
    service = FakeService()
    asyncio.run(
        connect_and_subscribe(
            service,  # type: ignore[arg-type]
            NAME,
            "http://slim.local:1234",
            SECRET,
        )
    )
    (config,), _ = service.connect_async.call_args
    assert config.endpoint == "http://slim.local:1234"
    service.create_app_with_secret.assert_called_once_with(NAME, SECRET)


def test_identity_is_passed_to_create_app() -> None:
    service = FakeService()
    identity = shared_secret_identity()
    run(service, identity=identity)

    service.create_app.assert_called_once_with(
        NAME, identity.provider, identity.verifier
    )
    service.create_app_with_secret.assert_not_called()


def test_client_config_is_passed_through() -> None:
    service = FakeService()
    client_config = slim_bindings.new_secure_client_config("https://slim.example:443")
    run(service, secret=SECRET, client_config=client_config)

    (config,), _ = service.connect_async.call_args
    assert config is client_config


def test_setup_slim_client_validates_before_initializing() -> None:
    with (
        mock.patch.object(helper, "initialize_slim_service") as init,
        pytest.raises(ValueError, match="credential is required"),
    ):
        asyncio.run(setup_slim_client("agntcy", "test", "unit"))
    init.assert_not_called()


def test_setup_slim_client_passes_options_through() -> None:
    service = FakeService()
    identity = shared_secret_identity()
    client_config = slim_bindings.new_secure_client_config("https://slim.example:443")

    async def fake_init(**_: object) -> FakeService:
        return service

    with mock.patch.object(helper, "initialize_slim_service", fake_init):
        _, app, name, conn_id = asyncio.run(
            setup_slim_client(
                "agntcy",
                "test",
                "unit",
                identity=identity,
                client_config=client_config,
            )
        )

    assert app is service.app
    assert conn_id == 7
    assert str(name) == str(NAME)
    (config,), _ = service.connect_async.call_args
    assert config is client_config
    service.create_app.assert_called_once()
    assert service.create_app.call_args.args[1:] == (
        identity.provider,
        identity.verifier,
    )
