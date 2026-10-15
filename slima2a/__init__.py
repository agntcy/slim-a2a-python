# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""SLIMA2A - A2A protocol over slimrpc."""

from slima2a.identity import SlimUser
from slima2a.slim_helper import (
    DEFAULT_SLIM_URL,
    SlimIdentity,
    connect_and_subscribe,
    initialize_slim_service,
    setup_slim_client,
)

__all__ = [
    "DEFAULT_SLIM_URL",
    "SlimIdentity",
    "SlimUser",
    "connect_and_subscribe",
    "initialize_slim_service",
    "setup_slim_client",
]
