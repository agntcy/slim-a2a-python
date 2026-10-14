# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""DefaultCallContextBuilder takes the caller from the verified session identity."""

from typing import cast

import pytest
import slim_bindings
from a2a.auth.user import UnauthenticatedUser
from a2a.extensions.common import HTTP_EXTENSION_HEADER

from slima2a import SlimUser
from slima2a.compat.v3_0.handler import (
    DefaultCallContextBuilder as DefaultCallContextBuilderV03,
)
from slima2a.handler import DefaultCallContextBuilder
from slima2a.identity import user_from_context

BUILDERS = [DefaultCallContextBuilder, DefaultCallContextBuilderV03]


class FakeContext:
    """Stands in for ``slim_bindings.Context``."""

    def __init__(
        self,
        subject: str | None = None,
        issuer: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._subject = subject
        self._issuer = issuer
        self._metadata = metadata or {}

    def peer_subject(self) -> str | None:
        return self._subject

    def peer_issuer(self) -> str | None:
        return self._issuer

    def metadata(self) -> dict[str, str]:
        return self._metadata


def _ctx(
    subject: str | None = None,
    issuer: str | None = None,
    metadata: dict[str, str] | None = None,
) -> slim_bindings.Context:
    return cast(slim_bindings.Context, FakeContext(subject, issuer, metadata))


@pytest.mark.parametrize("builder", BUILDERS)
def test_user_from_verified_subject_and_issuer(builder: type) -> None:
    context = _ctx(subject="agntcy/demo/client", issuer="https://issuer.example")
    call_context = builder().build(context)

    assert call_context.user == SlimUser("agntcy/demo/client", "https://issuer.example")
    assert call_context.user.is_authenticated
    assert call_context.user.user_name == "agntcy/demo/client"
    assert call_context.state["slim_context"] is context


@pytest.mark.parametrize("builder", BUILDERS)
def test_user_without_issuer(builder: type) -> None:
    user = builder().build(_ctx(subject="spiffe://example.org/client")).user

    assert isinstance(user, SlimUser)
    assert user.subject == "spiffe://example.org/client"
    assert user.issuer is None


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("subject", [None, ""])
def test_unauthenticated_without_subject(builder: type, subject: str | None) -> None:
    user = builder().build(_ctx(subject=subject, issuer="https://issuer.example")).user

    assert isinstance(user, UnauthenticatedUser)
    assert not user.is_authenticated


@pytest.mark.parametrize("builder", BUILDERS)
def test_metadata_is_never_identity(builder: type) -> None:
    # A caller can put anything in metadata; it must not become the user.
    spoofed = {
        "sub": "admin",
        "iss": "https://issuer.example",
        "user": "admin",
        "authorization": "Bearer admin",
        "x-slim-peer-subject": "admin",
    }
    assert isinstance(builder().build(_ctx(metadata=spoofed)).user, UnauthenticatedUser)
    assert builder().build(_ctx(subject="client", metadata=spoofed)).user == (
        SlimUser("client")
    )


@pytest.mark.parametrize("builder", BUILDERS)
def test_requested_extensions_from_metadata(builder: type) -> None:
    context = _ctx(metadata={HTTP_EXTENSION_HEADER: "urn:a, urn:b"})
    assert builder().build(context).requested_extensions == {"urn:a", "urn:b"}


def test_empty_issuer_is_none() -> None:
    assert user_from_context(FakeContext(subject="client", issuer="")) == SlimUser(
        "client"
    )


def test_slim_user_equality() -> None:
    assert SlimUser("a", "i") == SlimUser("a", "i")
    assert SlimUser("a", "i") != SlimUser("a", "j")
    assert SlimUser("a") != SlimUser("b")
    assert SlimUser("a") != UnauthenticatedUser()
    assert hash(SlimUser("a", "i")) == hash(SlimUser("a", "i"))
