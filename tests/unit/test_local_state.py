import pytest

from tasks.Controllers.LocalStateCtrl import LocalStateCtrl


@pytest.fixture(scope="session")
def tmp_abs_root_directory(tmp_path_factory):
    return tmp_path_factory.mktemp("tmp_root")


def test_create(monkeypatch, tmp_abs_root_directory):
    monkeypatch.setenv('GOCY_ROOT', tmp_abs_root_directory)

    local_state_ctrl = LocalStateCtrl()
    assert local_state_ctrl.cluster.name == 'kind-toem-capi-local'
    assert local_state_ctrl.constellation.name == 'jupiter'
