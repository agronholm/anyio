from anyio import sleep
from anyio.from_thread import start_blocking_portal

with start_blocking_portal() as portal:
    portal.call(sleep, 1)
