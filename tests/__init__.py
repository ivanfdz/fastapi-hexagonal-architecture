"""Test suite, mirroring the layers it exercises.

* ``tests/domain``         -- rules only. No fixtures, no I/O, no framework.
* ``tests/application``    -- use cases against real in-memory adapters and fakes.
* ``tests/infrastructure`` -- adapters: the repository contract suite and the HTTP API.

The distribution is the interesting part. Most of the assertions live in the two
inner layers, where they are fast and stable, and the outer layer only checks
translation. That shape is not discipline, it is a consequence of the dependency
rule: when the rules have no dependencies, testing them needs no setup.
"""
