import os
import shutil

from tasks.Controllers.ConstellationCtrl import get_constellation_by_name, get_cluster_by_name
from tasks.Controllers.ProjectPathCtrl import get_repo_dir, mkdirs
from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.DirTree import DirTree
from tasks.models.LocalState import LocalState


class LocalStateCtrl:
    _local_state: LocalState = LocalState()
    _dir_tree: DirTree

    def __init__(self, dir_tree: DirTree = None, file_name='state.yaml'):
        if dir_tree is None:
            self._dir_tree = DirTree(constellation=Constellation(name='jupiter'))
        else:
            self._dir_tree = dir_tree

        self._file_path = self._dir_tree.root(path=[file_name])
        if os.path.isfile(self._file_path):
            self._local_state = self._read()
        else:
            self._handle_initial_run()
            self._save()

    def _handle_initial_run(self):
        repo_tree = get_repo_dir()
        mkdirs(self._dir_tree)
        shutil.copy(
            repo_tree.templates(path=['secrets.yaml']),
            self._dir_tree.root()
        )
        shutil.copy(
            repo_tree.templates(path=['jupiter.constellation.yaml']),
            self._dir_tree.root()
        )

    def _read(self) -> LocalState:
        with open(self._file_path) as local_state_file:
            return LocalState.parse_raw(local_state_file.read())

    def _save(self):
        with open(self._file_path, 'w') as local_state_file:
            local_state_file.write(self._local_state.yaml())

    @property
    def constellation(self) -> Constellation:
        return get_constellation_by_name(self._local_state.constellation_context)

    @constellation.setter
    def constellation(self, constellation: Constellation):
        self._local_state.constellation_context = constellation.name
        self._save()

    @property
    def cluster(self) -> Cluster:
        return get_cluster_by_name(self._local_state.bary_cluster_context, self.constellation)

    @cluster.setter
    def cluster(self, cluster: Cluster):
        self._local_state.bary_cluster_context = cluster.name
        self._save()

