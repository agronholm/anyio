import ssl

import pytest
import trustme


@pytest.fixture(scope="session")
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture(scope="session")
def server_context(ca: trustme.CA) -> ssl.SSLContext:
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("localhost").configure_cert(server_context)
    return server_context


@pytest.fixture(scope="session")
def client_context(ca: trustme.CA) -> ssl.SSLContext:
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ca.configure_trust(client_context)
    return client_context
