"""Offline test: the network is blocked and complete cases run end to end."""

import socket

import pytest

from lockin_validate import run


class NetworkBlocked(RuntimeError):
    pass


def _block(*a, **k):
    raise NetworkBlocked("network blocked by the test")


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "socket", _block)
    monkeypatch.setattr(socket, "create_connection", _block)
    monkeypatch.setattr(socket, "getaddrinfo", _block)
    yield


def test_network_really_blocked(no_network):
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("pypi.org", 443), timeout=1)
    with pytest.raises(NetworkBlocked):
        socket.socket()


@pytest.mark.parametrize("case", ["core/10_independent", "core/09_lockin_style", "statistical/S01_noise_best_of_200",
                                  "data/D06_clean_extended_inputs"])
def test_full_case_offline(no_network, cases, tmp_path, case):
    res, paths = run(cases / case, tmp_path / "out")
    assert paths["markdown"].exists() and paths["json"].exists() and paths["html"].exists()
    text = paths["markdown"].read_text(encoding="utf-8")
    for section in ["## Scope", "## Inputs and versions (manifest)", "## Checks run", "## Confirmed errors",
                    "## Items that need human review", "## Checks not executable (missing information)",
                    "## Limitations and pending human review", "## Suggested actions (prioritised)"]:
        assert section in text
    assert len(res.checks()) >= 25
