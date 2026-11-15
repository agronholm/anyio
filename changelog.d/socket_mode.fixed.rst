Fixed race condition potentially allowing an attacker to change the access mode of an
arbitrary file via an attacker-created symlink during the creation of a local UNIX
socket when ``local_mode`` has been specified
(`GHSA-frm3-4vc3-wr3c <https://github.com/agronholm/sqlacodegen/security/advisories/GHSA-frm3-4vc3-wr3c>`_)
