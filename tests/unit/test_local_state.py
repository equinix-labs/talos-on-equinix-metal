import os.path

import pytest

from tasks.dao.SystemContext import SystemContext
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.models.Defaults import KIND_CLUSTER_NAME, CONSTELLATION_NAME, CONSTELLATION_FILE_SUFFIX, CLUSTER_NAME


@pytest.fixture(scope="session")
def tmp_abs_test_root(tmp_path_factory):
    return tmp_path_factory.mktemp("test_root")


def test_project_dir_created_ini_files_resent(monkeypatch, tmp_abs_test_root):
    project_dir = os.path.join(tmp_abs_test_root, 'project_dir')

    monkeypatch.setenv('GOCY_ROOT', project_dir)

    SystemContext(ProjectPaths(root=project_dir))

    assert os.path.isdir(project_dir)

    assert os.path.isfile(os.path.join(project_dir, 'state.yaml'))
    assert os.path.isfile(os.path.join(project_dir, '{}{}'.format(CONSTELLATION_NAME, CONSTELLATION_FILE_SUFFIX)))


def test_default_constellation_is_parsable(monkeypatch, tmp_abs_test_root):
    project_dir = os.path.join(tmp_abs_test_root, 'project_dir')

    monkeypatch.setenv('GOCY_ROOT', project_dir)

    local_state = SystemContext(ProjectPaths(root=project_dir))

    assert local_state.constellation.name == CONSTELLATION_NAME
    assert local_state.bary_cluster.name == KIND_CLUSTER_NAME
    assert local_state.cluster.name == KIND_CLUSTER_NAME
