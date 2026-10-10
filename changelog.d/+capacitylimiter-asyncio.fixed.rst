Fixed ``CapacityLimiter.acquire_on_behalf_of()`` on asyncio releasing the wrong
borrower when the acquiring task was cancelled during the cancel-shielded
checkpoint that runs after a non-blocking acquisition
