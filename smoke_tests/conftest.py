"""Windows compatibility shim for the real-HA smoke tests.

The HA test harness blocks socket *creation* (pytest-socket, unix sockets
exempted). On Windows the asyncio event loop itself needs an AF_INET
socketpair, so every test dies during setup before running. Neuter the
creation block and keep a connect-restriction to localhost instead — the
integration's network methods are mocked anyway.
"""
import asyncio
import sys
from pathlib import Path

import pytest_socket

# aiodns (used by aiohttp's resolver) requires a SelectorEventLoop on Windows;
# HA's own runner sets this policy in production, the test harness does not.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Make custom_components/ importable regardless of pytest's sys.path handling
sys.path.insert(0, str(Path(__file__).parent.parent))

# Bind the repo's custom_components namespace package NOW: the HA test harness
# later puts its own bundled custom_components (a regular package) on sys.path,
# which would otherwise shadow ours. First import wins in sys.modules.
import custom_components.eau_grand_lyon  # noqa: E402,F401

pytest_socket.disable_socket = lambda *args, **kwargs: None


def pytest_runtest_setup(item):
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"])
