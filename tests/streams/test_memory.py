import pytest

from anyio import create_task_group, wait_all_tasks_blocked, create_memory_object_stream
from anyio.exceptions import EndOfStream, ClosedResourceError, BrokenResourceError, WouldBlock

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
        await tg.spawn(receiver)
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
        await tg.spawn(receiver)
        await tg.spawn(receiver)
        await wait_all_tasks_blocked()
        await send.send_nowait('hello')
        await send.send_nowait('anyio')

    assert sorted(received_objects, reverse=True) == ['hello', 'anyio']


async def test_send_then_receive_nowait():
    send, receive = create_memory_object_stream(0)
    async with create_task_group() as tg:
        await tg.spawn(send.send, 'hello')
        await wait_all_tasks_blocked()
        assert await receive.receive_nowait() == 'hello'


async def test_send_is_unblocked_after_receive_nowait():
    send, receive = create_memory_object_stream(1)
    await send.send_nowait('hello')
    async with create_task_group() as tg:
        await tg.spawn(send.send, 'anyio')
        await wait_all_tasks_blocked()
        assert await receive.receive_nowait() == 'hello'
        await wait_all_tasks_blocked()
        assert len(receive._state.buffer) == 1


async def test_send_nowait_then_receive_nowait():
    send, receive = create_memory_object_stream(2)
    await send.send_nowait('hello')
    await send.send_nowait('anyio')
    assert await receive.receive_nowait() == 'hello'
    assert await receive.receive_nowait() == 'anyio'


async def test_iterate():
    async def receiver():
        async for item in receive:
            received_objects.append(item)

    send, receive = create_memory_object_stream()
    received_objects = []
    async with create_task_group() as tg:
        await tg.spawn(receiver)
        await send.send('hello')
        await send.send('anyio')
        await send.aclose()

    assert received_objects == ['hello', 'anyio']


async def test_receive_send_closed_send_stream():
    send, receive = create_memory_object_stream()
    await send.aclose()
    with pytest.raises(EndOfStream):
        await receive.receive_nowait()

    with pytest.raises(ClosedResourceError):
        await send.send(None)


async def test_receive_send_closed_receive_stream():
    send, receive = create_memory_object_stream()
    await receive.aclose()
    with pytest.raises(ClosedResourceError):
        await receive.receive_nowait()

    with pytest.raises(BrokenResourceError):
        await send.send(None)


async def test_cancel_receive():
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        await tg.spawn(receive.receive)
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()

    with pytest.raises(WouldBlock):
        await send.send_nowait('hello')


async def test_cancel_send():
    send, receive = create_memory_object_stream()
    async with create_task_group() as tg:
        await tg.spawn(send.send, 'hello')
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()

    with pytest.raises(WouldBlock):
        await receive.receive_nowait()


async def test_clone():
    send1, receive1 = create_memory_object_stream(1)
    send2 = send1.clone()
    receive2 = receive1.clone()
    await send1.aclose()
    await receive1.aclose()
    await send2.send_nowait('hello')
    assert await receive2.receive_nowait() == 'hello'


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
            await tg.spawn(receive.receive)
            await wait_all_tasks_blocked()
            await send.aclose()


async def test_close_receive_while_sending():
    send, receive = create_memory_object_stream(0)
    with pytest.raises(BrokenResourceError):
        async with create_task_group() as tg:
            await tg.spawn(send.send, 'hello')
            await wait_all_tasks_blocked()
            await receive.aclose()


async def test_receive_after_send_closed():
    send, receive = create_memory_object_stream(1)
    await send.send('hello')
    await send.aclose()
    assert await receive.receive() == 'hello'
