import os.path

import pytest

from tasks.Controllers.ProjectPathCtrl import get_config_dir, mkdirs
from tasks.models.ConstellationSpecV01 import Cluster, Constellation
from tasks.models.DirTree import DirTree


@pytest.fixture(scope="session")
def constellation():
    return Constellation(
        name='saturn',
        bary=Cluster(name='saturn'),
        satellites=[
            Cluster(name='titan'),
            Cluster(name='rhea')
        ])


@pytest.fixture(scope="session")
def tmp_abs_root_directory(tmp_path_factory):
    return tmp_path_factory.mktemp("tmp_root")


def test_dir_tree_repo():
    dir_tree = DirTree(repo=True)
    assert dir_tree.apps() == os.path.join(
        os.getcwd(),
        'apps'
    )


def test_config_dir_from_absolute_root_env(monkeypatch, constellation, tmp_abs_root_directory):
    monkeypatch.setenv('GOCY_ROOT', tmp_abs_root_directory)

    cfg_dir = get_config_dir(constellation=constellation)
    assert cfg_dir.root() == os.getenv('GOCY_ROOT')


def test_config_dir_from_absolute_root(constellation):
    dir_tree = DirTree("/tmp/gocy", constellation)
    assert dir_tree.patch(Cluster(name='rhea')) == os.path.join(
            '/tmp/gocy',
            'saturn',
            'rhea',
            'patch'
        )


def test_config_dir_constellation_root(constellation):
    dir_tree = DirTree(root='tmp_root', constellation=constellation)

    assert dir_tree.constellation() == os.path.join(
            os.path.expanduser('~'),
            'tmp_root',
            'saturn'
        )


def test_config_dir_cluster_root(constellation):
    dir_tree = DirTree(root='.gocy_tmp_root', constellation=constellation)

    assert dir_tree.patch(Cluster(name='titan')) == os.path.join(
            os.path.expanduser('~'),
            '.gocy_tmp_root',
            'saturn',
            'titan',
            'patch'
        )


def test_dir_tree_config_sub_dir(constellation):
    dir_tree = DirTree(constellation=constellation)
    assert dir_tree.patch(Cluster(name='rhea'), ['bgp']) == os.path.join(
            os.path.expanduser('~'),
            '.gocy',
            'saturn',
            'rhea',
            'patch',
            'bgp'
        )


def test_dir_tree_can_have_state(constellation):
    dir_tree = DirTree(constellation=constellation)
    assert dir_tree.patch(cluster=Cluster(name='titan'), path=['bgp', 'something']) == os.path.join(
            os.path.expanduser('~'),
            '.gocy',
            'saturn',
            'titan',
            'patch',
            'bgp',
            'something'
        )


def test_dir_tree_returns_paths(constellation, tmp_abs_root_directory):
    dir_tree = DirTree(root=tmp_abs_root_directory, constellation=constellation)
    mkdirs(dir_tree)

    assert os.path.isdir(dir_tree.constellation())
    mkdirs(dir_tree.cluster(Cluster(name='rhea')))

    assert os.path.isdir(dir_tree.cluster(Cluster(name='rhea')))
