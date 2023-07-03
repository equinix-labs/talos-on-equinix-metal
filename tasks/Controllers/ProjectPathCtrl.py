import logging
import os.path
from typing import Any

from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.DirTree import DirTree


class ProjectPathCtrl:
    _constellation: Constellation
    _cluster: Cluster
    _root: str

    def __init__(self, constellation: Constellation, cluster: Cluster, root=None):
        self._constellation = constellation
        self._cluster = cluster
        if root is None:
            self._root = os.environ.get('GOCY_ROOT', '.gocy')

        mkdirs(DirTree(root=self._root, constellation=self._constellation, cluster=self._cluster))

    def get_vips_file_path_by_role(self, address_role):
        path = DirTree(root=self._root, constellation=self._constellation, cluster=self._cluster).constellation(
            path=["vips-{}.yaml".format(address_role)]
        )
        mkdirs(path)
        return path

    def get_project_vips(self):
        return DirTree(self._root, self._constellation, self._cluster).constellation(
            path=['vips-project.yaml']
        )

    def get_constellation_path(self):
        return DirTree(root=self._root, constellation=self._constellation).constellation()

    def get_cluster_path(self):
        return DirTree(root=self._root, constellation=self._constellation).constellation()

    def get_capi_manifest_file_path(self):
        return DirTree(root=self._root, constellation=self._constellation).cluster(path=['cluster-manifest.yaml'])


def get_secrets_file_path(name='secrets.yaml'):
    return DirTree().root(path=[name])


def get_repo_dir() -> DirTree:
    return DirTree(repo=True)


def get_config_dir(constellation: Constellation, root=None):
    if root is None:
        root = os.environ.get('GOCY_ROOT', '.gocy')

    return DirTree(root=root, constellation=constellation)


def mkdirs(dir_tree: Any):
    if type(dir_tree) is not DirTree:
        if not os.path.isdir(dir_tree):
            os.makedirs(dir_tree)
            logging.debug("Created directory: " + dir_tree)
    else:
        object_methods = [method_name for method_name in dir(dir_tree)
                          if callable(getattr(dir_tree, method_name))]

        for method_name in object_methods:
            if not method_name.startswith("_"):
                path_method = getattr(dir_tree, method_name)
                path = path_method()
                if not os.path.isdir(path):
                    os.makedirs(path, exist_ok=True)
                    logging.debug("Created directory: " + path)
