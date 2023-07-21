import base64
import os.path

import pytest
from invoke import Context

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.wrappers.OpenSSL import OpenSSL


@pytest.fixture(scope="session")
def tmp_abs_root_directory(tmp_path_factory):
    return tmp_path_factory.mktemp("tmp_root")


def test_create_ca(tmp_abs_root_directory):
    paths = ProjectPaths(constellation_name='jupiter', root=tmp_abs_root_directory)
    ctx = Context()
    state = SystemContext(ctx, True, paths)
    openssl = OpenSSL(state, ctx, True)

    openssl.create()

    assert os.path.isfile(paths.ca_crt_file()) is True
    assert os.path.isfile(paths.ca_key_file()) is True

    ca_crt_b64 = openssl.get_ca_crt_as_b64()

    with open(paths.ca_crt_file()) as ca_crt_file:
        ca_crt = ca_crt_file.read()

    ca_crt_from_b64 = base64.b64decode(ca_crt_b64).decode('utf-8')
    assert ca_crt_from_b64 == ca_crt
