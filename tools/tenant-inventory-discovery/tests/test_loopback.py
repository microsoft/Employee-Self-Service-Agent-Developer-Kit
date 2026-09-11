"""Loopback classification, which decides TLS verification.

The dev tunnel serves a self-signed certificate. ``httpx`` validates against ``certifi``
rather than the Windows certificate store that PowerShell and Insomnia use, so it
rejects a host those tools reach happily -- which reads as "the service is down" instead
of "the trust stores differ".

Relaxing verification for loopback only is what keeps that convenience from becoming a
hazard, so the interesting cases here are the ones that must *not* be treated as local.
"""

from __future__ import annotations

import pytest

from tenant_inventory_discovery.config import is_loopback_url


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:444/weveb2",
        "https://localhost/weveb2",
        "http://127.0.0.1:8080",
        "https://[::1]:444/weveb2",
        "https://LOCALHOST:444/weveb2",
    ],
)
def test_local_targets(url):
    assert is_loopback_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://substrate.office.com/weveb2",
        # Substring matching would make every one of these look local.
        "https://localhost.evil.test/weveb2",
        "https://notlocalhost/weveb2",
        "https://127.0.0.1.evil.test/weveb2",
        # Credentials in the userinfo section must not be read as the host.
        "https://localhost@evil.test/weveb2",
        "https://10.0.0.5/weveb2",
    ],
)
def test_remote_targets(url):
    assert is_loopback_url(url) is False


@pytest.mark.parametrize("url", [None, "", "not a url"])
def test_unusable_input_is_not_local(url):
    """Default to verifying: an unparseable target is not evidence of safety."""
    assert is_loopback_url(url) is False
