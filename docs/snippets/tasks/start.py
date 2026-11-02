from anyio import (
    TASK_STATUS_IGNORED,
    connect_tcp,
    create_task_group,
    create_tcp_listener,
    run,
)
from anyio.abc import SocketStream, TaskStatus


async def handler(stream: SocketStream) -> None: ...


async def start_some_service(
    port: int, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED
) -> None:
    async with await create_tcp_listener(
        local_host="127.0.0.1", local_port=port
    ) as listener:
        task_status.started()
        await listener.serve(handler)


async def main() -> None:
    async with create_task_group() as tg:
        await tg.start(start_some_service, 5000)
        async with await connect_tcp("127.0.0.1", 5000) as stream:
            ...


run(main)
