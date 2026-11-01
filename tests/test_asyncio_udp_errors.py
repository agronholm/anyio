from __future__ import annotations

import errno
from collections.abc import AsyncIterator

import pytest
from _pytest.fixtures import SubRequest
from pytest_mock import MockerFixture

from anyio import (
    BrokenResourceError,
    ClosedResourceError,
    Event,
    create_connected_udp_socket,
    create_task_group,
    create_udp_socket,
    fail_after,
    wait_all_tasks_blocked,
)
from anyio._backends._asyncio import ConnectedUDPSocket as AsyncConnectedUDPSocket
from anyio._backends._asyncio import UDPSocket as AsyncUDPSocket
from anyio.abc import ConnectedUDPSocket, SocketAttribute, UDPSocket

from .conftest import asyncio_params

pytestmark = pytest.mark.parametrize("anyio_backend", asyncio_params)
DatagramSocket = AsyncUDPSocket | AsyncConnectedUDPSocket


@pytest.fixture(params=[False, True], ids=["unconnected", "connected"])
async def udp_pair(
    request: SubRequest,
) -> AsyncIterator[tuple[DatagramSocket, UDPSocket]]:
    async with await create_udp_socket(local_host="127.0.0.1") as peer:
        udp: UDPSocket | ConnectedUDPSocket
        if request.param:
            udp = await create_connected_udp_socket(
                "127.0.0.1", peer.extra(SocketAttribute.local_port)
            )
        else:
            udp = await create_udp_socket(local_host="127.0.0.1")

        assert isinstance(udp, (AsyncUDPSocket, AsyncConnectedUDPSocket))
        async with udp:
            yield udp, peer


async def send_datagram(udp: DatagramSocket, peer: UDPSocket) -> None:
    if isinstance(udp, AsyncConnectedUDPSocket):
        await udp.send(b"payload")
    else:
        await udp.sendto(
            b"payload", "127.0.0.1", peer.extra(SocketAttribute.local_port)
        )


async def test_send_reports_pending_error(
    udp_pair: tuple[DatagramSocket, UDPSocket],
) -> None:
    udp, peer = udp_pair
    error = OSError(errno.ECONNREFUSED, "Connection refused")
    udp._protocol.error_received(error)

    with pytest.raises(BrokenResourceError) as exc:
        await send_datagram(udp, peer)

    assert exc.value.__cause__ is error


@pytest.mark.parametrize("error_already_pending", [False, True])
async def test_error_wakes_receive(
    udp_pair: tuple[DatagramSocket, UDPSocket],
    error_already_pending: bool,
) -> None:
    udp, _ = udp_pair
    error = OSError(errno.ECONNREFUSED, "Connection refused")
    if error_already_pending:
        udp._protocol.error_received(error)

    async def receive() -> None:
        with pytest.raises(BrokenResourceError) as exc:
            await udp.receive()

        assert exc.value.__cause__ is error

    with fail_after(2):
        async with create_task_group() as tg:
            tg.start_soon(receive)
            if not error_already_pending:
                await wait_all_tasks_blocked()
                udp._protocol.error_received(error)


async def test_send_reports_error_from_transport(
    udp_pair: tuple[DatagramSocket, UDPSocket], mocker: MockerFixture
) -> None:
    udp, peer = udp_pair
    error = OSError(errno.ECONNREFUSED, "Connection refused")

    def fail_send(*args: object) -> None:
        udp._protocol.error_received(error)

    transport = mocker.Mock(wraps=udp._transport)
    transport.sendto.side_effect = fail_send
    mocker.patch.object(udp, "_transport", transport)
    with pytest.raises(BrokenResourceError) as exc:
        await send_datagram(udp, peer)

    assert exc.value.__cause__ is error


async def test_only_latest_error_is_reported_and_socket_remains_usable(
    udp_pair: tuple[DatagramSocket, UDPSocket],
) -> None:
    udp, peer = udp_pair
    for _ in range(3):
        error = OSError(errno.ECONNREFUSED, "Connection refused")
        udp._protocol.error_received(error)

    with pytest.raises(BrokenResourceError) as exc:
        await send_datagram(udp, peer)

    assert exc.value.__cause__ is error
    with fail_after(2):
        await send_datagram(udp, peer)
        assert (await peer.receive())[0] == b"payload"


@pytest.mark.parametrize("pause_before_send", [False, True])
async def test_error_wakes_paused_send_without_losing_backpressure(
    udp_pair: tuple[DatagramSocket, UDPSocket],
    pause_before_send: bool,
    mocker: MockerFixture,
) -> None:
    udp, peer = udp_pair
    error = OSError(errno.ECONNREFUSED, "Connection refused")
    if pause_before_send:
        udp._protocol.pause_writing()
    else:
        transport = mocker.Mock(wraps=udp._transport)

        def pause_send(*args: object) -> None:
            udp._protocol.pause_writing()
            transport.sendto.side_effect = None

        transport.sendto.side_effect = pause_send
        mocker.patch.object(udp, "_transport", transport)

    sent = Event()

    async def send_with_error() -> None:
        with pytest.raises(BrokenResourceError) as exc:
            await send_datagram(udp, peer)

        assert exc.value.__cause__ is error

    async def send_after_error() -> None:
        await send_datagram(udp, peer)
        sent.set()

    with fail_after(2):
        async with create_task_group() as tg:
            tg.start_soon(send_with_error)
            await wait_all_tasks_blocked()
            udp._protocol.error_received(error)

        async with create_task_group() as tg:
            tg.start_soon(send_after_error)
            await wait_all_tasks_blocked()
            assert not sent.is_set()
            udp._protocol.resume_writing()

        assert (await peer.receive())[0] == b"payload"


async def test_error_consumed_by_sender_does_not_fail_waiting_receiver(
    udp_pair: tuple[DatagramSocket, UDPSocket],
) -> None:
    udp, peer = udp_pair
    received: bytes | tuple[bytes, object] | None = None

    async def receive() -> None:
        nonlocal received
        received = await udp.receive()

    with fail_after(2):
        async with create_task_group() as tg:
            tg.start_soon(receive)
            await wait_all_tasks_blocked()
            udp._protocol.error_received(
                OSError(errno.ECONNREFUSED, "Connection refused")
            )
            with pytest.raises(BrokenResourceError):
                await send_datagram(udp, peer)

            await peer.sendto(
                b"reply", "127.0.0.1", udp.extra(SocketAttribute.local_port)
            )

    assert received == (
        b"reply"
        if isinstance(udp, AsyncConnectedUDPSocket)
        else (b"reply", peer.extra(SocketAttribute.local_address))
    )


async def test_closed_socket_takes_precedence_over_pending_error(
    udp_pair: tuple[DatagramSocket, UDPSocket],
) -> None:
    udp, peer = udp_pair
    udp._protocol.error_received(OSError(errno.ECONNREFUSED, "Connection refused"))
    await udp.aclose()

    with pytest.raises(ClosedResourceError):
        await udp.receive()

    with pytest.raises(ClosedResourceError):
        await send_datagram(udp, peer)
