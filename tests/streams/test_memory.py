import pytest

from anyio import (
    BrokenResourceError, CancelScope, ClosedResourceError, EndOfStream, WouldBlock,
    create_memory_object_stream, create_task_group, fail_after, wait_all_tasks_blocked)

pytestmark = pytest.mark.anyio


def test_invalid_max_buffer():
    pytest.raises(ValueError, create_memory_object_stream, 1.0).\
        match('max_buffer_size must be either an integer or math.inf')


def test_negative_max_buffer():
    pytest.raises(ValueError, create_memory_object_stream, -1).\
        match('max_buffer_size cannot be negative')


async def test_receive_then_send():
    async def receiver():
        received_objects.append(await receive.receive())
        received_objects.append(await receive.receive())

    send, receive = create_memory_object_stream(0)
    received_objects = []
    async with create_task_group() as tg:
        tg.spawn(receiver)
        await wait_all_tasks_blocked()
        await send.send('hello')
        await send.send('anyio')

    assert received_objects == ['hello', 'anyio']


async def test_receive_then_send_nowait():
    async def receiver():
        received_objects.append(await receive.receive())

    send, receive = create_memory_object_stream(0)
    received_objects = []
    async with create_task_group() as tg:
        tg.spawn(receiver)
        tg.spawn(receiver)
        await wait_all_tasks_blocked()
        send.send_nowait('hello')
        send.send_nowait('anyio')

    assert sorted(received_objects, reverse=True) == ['hello', 'anyio']


async def test_send_then_receive_nowait():
    send, receive = create_memory_object_stream(0)
    async with create_task_group() as tg:
        tg.spawn(send.send, 'hello')
        await wait_all_tasks_blocked()
        assert receive.receive_nowait() == 'hello'


async def test_send_is_unblocked_after_receive_nowait():
    send, receive = create_memory_object_stream(1)
    send.send_nowait('hello')

    with fail_after(1):
        async with create_task_group() as tg:
            tg.spawn(send.send, 'anyio')
            await wait_all_tasks_blocked()
            assert receive.receive_nowait() == 'hello'

    assert receive.receive_nowait() == 'anyio'


async def test_send_nowait_then_receive_nowait():
    send, receive = create_memory_object_stream(2)
    send.send_nowait('hello')
    send.send_nowait('anyio')
    assert receive.receive_nowait() == 'hello'
    assert receive.receive_nowait() == 'anyio'


async def test_iterate():
    async def receiver():
        async for item in receive:
            received_objects.append(item)

    send, receive = create_memory_object_stream()
    received_objects = []
    async with create_task_group() as tg:
        tg.spawn(receiver)
        await send.send('hello')
        await send.send('anyio')
        await send.aclose()

    assert received_objects == ['hello', 'anyio']


async def test_receive_send_closed_send_stream():
    send, receive = create_memory_object_stream()
    await send.aclose()
    with pytest.raises(EndOfStream):
        receive.receive_nowait()

    with pytest.raises(ClosedResourceError):
        await send.send(None)


async def test_receive_send_closed_receive_stream():
    send, receive = create_memory_object_stream()
    await receive.aclose()
    with pytest.raises(ClosedResourceError):
        receive.receive_nowait()

    with pytest.raises(BrokenResourceError):
        await send.send(None)


async def test_cancel_receive():
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(receive.receive)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    with pytest.raises(WouldBlock):
        send.send_nowait('hello')


async def test_cancel_send():
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(send.send, 'hello')
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    with pytest.raises(WouldBlock):
        receive.receive_nowait()


async def test_clone():
    send1, receive1 = create_memory_object_stream(1)
    send2 = send1.clone()
    receive2 = receive1.clone()
    await send1.aclose()
    await receive1.aclose()
    send2.send_nowait('hello')
    assert receive2.receive_nowait() == 'hello'


async def test_clone_closed():
    send, receive = create_memory_object_stream(1)
    await send.aclose()
    await receive.aclose()
    pytest.raises(ClosedResourceError, send.clone)
    pytest.raises(ClosedResourceError, receive.clone)


async def test_close_send_while_receiving():
    send, receive = create_memory_object_stream(1)
    with pytest.raises(EndOfStream):
        async with create_task_group() as tg:
            tg.spawn(receive.receive)
            await wait_all_tasks_blocked()
            await send.aclose()


async def test_close_receive_while_sending():
    send, receive = create_memory_object_stream(0)
    with pytest.raises(BrokenResourceError):
        async with create_task_group() as tg:
            tg.spawn(send.send, 'hello')
            await wait_all_tasks_blocked()
            await receive.aclose()


async def test_receive_after_send_closed():
    send, receive = create_memory_object_stream(1)
    await send.send('hello')
    await send.aclose()
    assert await receive.receive() == 'hello'


async def test_receive_when_cancelled():
    """
    Test that calling receive() in a cancelled scope prevents it from going through with the
    operation.

    """
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(send.send, 'hello')
        await wait_all_tasks_blocked()
        tg.spawn(send.send, 'world')
        await wait_all_tasks_blocked()

        with CancelScope() as scope:
            scope.cancel()
            await receive.receive()

        assert await receive.receive() == 'hello'
        assert await receive.receive() == 'world'


async def test_send_when_cancelled():
    """
    Test that calling send() in a cancelled scope prevents it from going through with the
    operation.

    """
    async def receiver():
        received.append(await receive.receive())

    received = []
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(receiver)
        with CancelScope() as scope:
            scope.cancel()
            await send.send('hello')

        await send.send('world')

    assert received == ['world']


async def test_cancel_during_receive():
    """
    Test that cancelling a pending receive() operation does not cause an item in the stream to be
    lost.

    """
    async def scoped_receiver():
        nonlocal receiver_scope
        with CancelScope() as receiver_scope:
            received.append(await receive.receive())

        assert receiver_scope.cancel_called

    receiver_scope = None
    received = []
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(scoped_receiver)
        await wait_all_tasks_blocked()
        send.send_nowait('hello')
        receiver_scope.cancel()

    assert received == ['hello']


async def test_close_receive_after_send():
    async def send() -> None:
        async with send_stream:
            await send_stream.send('test')

    async def receive() -> None:
        async with receive_stream:
            assert await receive_stream.receive() == 'test'

    send_stream, receive_stream = create_memory_object_stream()
    async with create_task_group() as tg:
        tg.spawn(send)
        tg.spawn(receive)


async def test_statistics():
    send_stream, receive_stream = create_memory_object_stream(1)
    for stream in send_stream, receive_stream:
        statistics = stream.statistics()
        assert statistics.max_buffer_size == 1
        assert statistics.current_buffer_used == 0
        assert statistics.open_send_streams == 1
        assert statistics.open_receive_streams == 1
        assert statistics.tasks_waiting_send == 0
        assert statistics.tasks_waiting_receive == 0

    for stream in send_stream, receive_stream:
        async with create_task_group() as tg:
            # Test tasks_waiting_send
            send_stream.send_nowait(None)
            assert stream.statistics().current_buffer_used == 1
            tg.spawn(send_stream.send, None)
            await wait_all_tasks_blocked()
            assert stream.statistics().current_buffer_used == 1
            assert stream.statistics().tasks_waiting_send == 1
            receive_stream.receive_nowait()
            assert stream.statistics().current_buffer_used == 1
            assert stream.statistics().tasks_waiting_send == 0
            receive_stream.receive_nowait()
            assert stream.statistics().current_buffer_used == 0

            # Test tasks_waiting_receive
            tg.spawn(receive_stream.receive)
            await wait_all_tasks_blocked()
            assert stream.statistics().tasks_waiting_receive == 1
            send_stream.send_nowait(None)
            assert stream.statistics().tasks_waiting_receive == 0

        async with create_task_group() as tg:
            # Test tasks_waiting_send
            send_stream.send_nowait(None)
            assert stream.statistics().tasks_waiting_send == 0
            for _ in range(3):
                tg.spawn(send_stream.send, None)

            await wait_all_tasks_blocked()
            assert stream.statistics().tasks_waiting_send == 3
            for i in range(2, -1, -1):
                receive_stream.receive_nowait()
                assert stream.statistics().tasks_waiting_send == i

            receive_stream.receive_nowait()

        assert stream.statistics().current_buffer_used == 0
        assert stream.statistics().tasks_waiting_send == 0
        assert stream.statistics().tasks_waiting_receive == 0
