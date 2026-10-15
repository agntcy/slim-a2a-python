# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""The verified identity of a slimrpc caller."""

from typing import Protocol

from a2a.auth.user import UnauthenticatedUser, User


class _PeerIdentityContext(Protocol):
    def peer_subject(self) -> str | None: ...
    def peer_issuer(self) -> str | None: ...


class SlimUser(User):
    """A caller authenticated by SLIM.

    ``subject`` and ``issuer`` are the ``sub`` and ``iss`` claims of the token
    the caller's app used to set up the MLS session, as verified by this app's
    identity verifier. ``user_name`` is the subject.
    """

    def __init__(self, subject: str, issuer: str | None = None) -> None:
        self.subject = subject
        self.issuer = issuer

    @property
    def is_authenticated(self) -> bool:
        """Always ``True``: SLIM verified the caller's token."""
        return True

    @property
    def user_name(self) -> str:
        """The caller's verified subject."""
        return self.subject

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SlimUser)
            and other.subject == self.subject
            and other.issuer == self.issuer
        )

    def __hash__(self) -> int:
        return hash((self.subject, self.issuer))

    def __repr__(self) -> str:
        return f"SlimUser(subject={self.subject!r}, issuer={self.issuer!r})"


def user_from_context(context: _PeerIdentityContext) -> User:
    """The caller of a slimrpc request, from its verified session identity.

    Returns a :class:`SlimUser` built from ``Context.peer_subject()`` and
    ``Context.peer_issuer()``, or ``UnauthenticatedUser`` when the session
    carries no verified subject. In a group session the subject is the MLS
    sender of the request. Caller-supplied metadata is never used.
    """
    subject = context.peer_subject()
    if not subject:
        return UnauthenticatedUser()
    return SlimUser(subject, context.peer_issuer() or None)
