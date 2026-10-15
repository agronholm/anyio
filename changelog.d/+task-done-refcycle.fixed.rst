Fixed a reference cycle that kept the frames of a cancelled child task alive until
the cyclic garbage collector ran, on the asyncio backend with Python 3.11 and later
