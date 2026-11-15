Fixed race condition potentially allowing an attacker to change the access mode of an
arbitrary file via an attacker-created symlink during the creation of a local UNIX
socket when ``local_mode`` has been specified
(`GHSA-rj4j-hmqp-rh3q <https://github.com/agronholm/anyio/security/advisories/GHSA-rj4j-hmqp-rh3q>`_)
