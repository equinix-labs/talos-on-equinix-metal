import os
import shutil

from pydantic import ValidationError
from pydantic_yaml import YamlModel

from tasks.controllers.ConstellationCtrl import ConstellationCtrl, get_constellation_spec_file_paths
from tasks.dao.ProjectPaths import mkdirs, ProjectPaths, RepoPaths
from tasks.models.ConstellationSpecV01 import Constellation, Cluster
from tasks.models.Defaults import CONSTELLATION_NAME, CONSTELLATION_FILE_SUFFIX, KIND_CLUSTER_NAME


class LocalStateModel(YamlModel):
    constellation_context: str = CONSTELLATION_NAME
    bary_cluster_context: str = KIND_CLUSTER_NAME


class LocalState:
    _project_paths: ProjectPaths
    _local_state: LocalStateModel

    def __init__(self, project_paths: ProjectPaths = None):
        if project_paths is None:
            self._project_paths = ProjectPaths()
        else:
            self._project_paths = project_paths

        if os.path.isfile(self._project_paths.state_file()):
            self._read()
            self._project_paths = ProjectPaths(
                self._local_state.constellation_context,
                self._local_state.bary_cluster_context,
                self._project_paths.project_root()
            )
        else:
            self._local_state = LocalStateModel()
            self._project_paths = ProjectPaths(
                self._local_state.constellation_context,
                self._local_state.bary_cluster_context,
                self._project_paths.project_root()
            )
            self._handle_initial_run()
            self._save()

    def _handle_initial_run(self):
        repo_paths = RepoPaths()
        mkdirs(self._project_paths.project_root())
        shutil.copy(
            repo_paths.templates_dir('secrets.yaml'),
            self._project_paths.project_root()
        )
        shutil.copy(
            repo_paths.templates_dir('{}{}'.format(CONSTELLATION_NAME, CONSTELLATION_FILE_SUFFIX)),
            self._project_paths.project_root()
        )

    def _read(self):
        with open(self._project_paths.state_file()) as local_state_file:
            self._local_state = LocalStateModel.parse_raw(local_state_file.read())

    def _save(self):
        mkdirs(self._project_paths.constellation_dir())
        with open(self._project_paths.state_file(), 'w') as local_state_file:
            local_state_file.write(self._local_state.yaml())

    @property
    def constellation(self) -> Constellation:
        const_ctrl = ConstellationCtrl(
            self._project_paths,
            self._local_state.constellation_context
        )
        return const_ctrl.constellation

    @constellation.setter
    def constellation(self, constellation: Constellation):
        self._local_state.constellation_context = constellation.name
        self._save()

    def constellation_set(self, constellation_name: str):
        written = False
        for constellation_spec_file in get_constellation_spec_file_paths():
            try:
                constellation = Constellation.parse_raw(constellation_spec_file.read())
                if constellation.name == constellation_name:
                    self.constellation = constellation
                    mkdirs(ProjectPaths(constellation_name=constellation_name).constellation_dir())
                    written = True
            except ValidationError:
                pass
        if not written:
            print("Context not set, make sure the NAME is correct,"
                  " and matches spec file ~/[GOCY_DIR]/[NAME].constellation.yaml")

    @property
    def cluster(self) -> Cluster:
        const_ctrl = ConstellationCtrl(self._project_paths, self._local_state.constellation_context)
        return const_ctrl.get_cluster_by_name(self._local_state.bary_cluster_context)

    @cluster.setter
    def cluster(self, cluster: Cluster):
        self._local_state.bary_cluster_context = cluster.name
        self._save()
