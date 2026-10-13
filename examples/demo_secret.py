# Copyright AGNTCY Contributors (https://github.com/agntcy)
# SPDX-License-Identifier: Apache-2.0

"""Shared secret used by the examples.

TEST-ONLY: ``DEMO_SECRET`` is the publicly known placeholder that the sibling
slim-a2a SDK examples also use, so the examples interoperate locally across
languages. Never use it outside a local demo. The library itself has no
default secret; set ``SLIM_SHARED_SECRET`` (or pass ``--secret`` where the
example supports it) to use your own.
"""

import os

DEMO_SECRET = "secretsecretsecretsecretsecretsecret"  # test-only, publicly known


def default_secret() -> str:
    """Return ``$SLIM_SHARED_SECRET`` if set, else the demo-only placeholder."""
    return os.environ.get("SLIM_SHARED_SECRET") or DEMO_SECRET
