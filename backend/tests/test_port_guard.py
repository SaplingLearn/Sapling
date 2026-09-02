"""
Dev-entrypoint port guard (main.py::_refuse_if_port_taken).

Windows lets a second process bind a port another process is already listening
on and hands it no traffic, so `python main.py` against an occupied port starts
a server that looks healthy and answers nobody. The guard's only job is to say
so before that happens — which means it has to actually FIND the other server.

The IPv6 case is the reason these tests exist. The first version of the guard
probed AF_INET/127.0.0.1 only, so a stale server bound to ::1 (which is what
`localhost` resolves to first on a dual-stack box) sailed straight past it and
the guard reported "port free" for precisely the situation it was written for.
"""
import socket

import pytest

from main import _refuse_if_port_taken


def _free_port() -> int:
    """A port nothing is listening on.

    Bind-then-close rather than a hardcoded number: a fixed port is exactly the
    kind of assumption that makes this suite fail on a developer's machine that
    happens to be running something there.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ipv6_loopback_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


class TestRefuseIfPortTaken:
    def test_free_port_returns(self):
        _refuse_if_port_taken(_free_port())

    def test_occupied_ipv4_loopback_exits(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with pytest.raises(SystemExit) as exc:
                _refuse_if_port_taken(port)
        assert str(port) in str(exc.value)

    @pytest.mark.skipif(
        not _ipv6_loopback_available(), reason="host has no IPv6 loopback"
    )
    def test_occupied_ipv6_loopback_exits(self):
        # The regression: an AF_INET-only probe of 127.0.0.1 cannot see this
        # listener, so the guard used to return "free" while `localhost:<port>`
        # in a browser reached the stale server.
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as server:
            server.bind(("::1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with pytest.raises(SystemExit) as exc:
                _refuse_if_port_taken(port)
        # The message names the address that answered — without it the next
        # person is told "already serving" and has to guess which family to go
        # hunting on.
        assert "::1" in str(exc.value)

    def test_message_names_the_port_and_how_to_free_it(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with pytest.raises(SystemExit) as exc:
                _refuse_if_port_taken(port)
        message = str(exc.value)
        assert f"lsof -ti tcp:{port}" in message
        assert "Get-NetTCPConnection" in message
