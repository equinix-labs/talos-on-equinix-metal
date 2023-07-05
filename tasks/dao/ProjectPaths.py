import logging
import os.path

from tasks.models.ConstellationSpecV01 import VipRole
from tasks.models.Defaults import CONSTELLATION_FILE_SUFFIX


def get_repo_dir() -> str:
    return os.getcwd()


class RepoPaths:

    _root: str

    def __init__(self):
        self._root = os.getcwd()

    def templates_dir(self, *path):
        return os.path.join(self._root, 'templates', *path)

    def capi_control_plane_template(self):
        return self.templates_dir('cluster', 'capi-control-plane.yaml')

    def capi_machines_template(self):
        return self.templates_dir('cluster', 'capi-machines.yaml')

    def apps_dir(self, *path):
        return os.path.join(self._root, 'apps', *path)


class ProjectPaths:
    _constellation_name: str
    _cluster_name: str
    _root: str

    def __init__(self, constellation_name: str = None, cluster_name: str = None, root=None):
        self._constellation_name = constellation_name
        self._cluster_name = cluster_name
        if root is None:
            self._root = os.environ.get('GOCY_ROOT', os.path.join(
                os.path.expanduser('~'),
                '.gocy'
            ))
        else:
            if os.path.isabs(root):
                self._root = root
            else:
                self._root = os.path.join(
                    os.path.expanduser('~'),
                    root
                )

    def project_root(self, *paths):
        return os.path.join(self._root, *paths)

    def secrets_file(self):
        return os.path.join(self.project_root(), 'secrets.yaml')

    def state_file(self):
        return os.path.join(self.project_root(), 'state.yaml')

    def constellation_dir(self):
        return os.path.join(self.project_root(), self._constellation_name)

    def constellation_file(self, name: str):
        return os.path.join(self.project_root(), "{}{}".format(name, CONSTELLATION_FILE_SUFFIX))

    def cluster_dir(self):
        return os.path.join(self.constellation_dir(), self._cluster_name)

    def cluster_capi_manifest_file(self):
        return os.path.join(self.cluster_dir(), "capi-manifest.yaml")

    def k8s_manifests_dir(self):
        return os.path.join(self.cluster_dir(), "k8s_manifests")

    def patches_dir(self, *paths):
        return os.path.join(self.cluster_dir(), "patch", *paths)

    def templates_dir(self):
        return os.path.join(self.cluster_dir(), "templates")

    def apps_dir(self, *paths):
        return os.path.join(self.cluster_dir(), "apps", *paths)

    def talos_dir(self):
        return os.path.join(self.cluster_dir(), "talos")

    def access_dir(self):
        return os.path.join(self.cluster_dir(), "access")

    def argo_apps_dir(self):
        return os.path.join(self.cluster_dir(), "argo", "apps")

    def argo_infra_dir(self):
        return os.path.join(self.cluster_dir(), "argo", "infra")

    def cluster_capi_static_manifest_file(self):
        return os.path.join(mkdirs(self.argo_infra_dir()), "capi-manifest.static.yaml")

    def vips_file_by_role(self, address_role: VipRole):
        return os.path.join(self.cluster_dir(), "vips-{}.yaml".format(address_role))

    def project_vips_file(self):
        return os.path.join(mkdirs(self.cluster_dir()), 'vips-project.yaml')

    def capi_manifest_file(self):
        return os.path.join(self.cluster_dir(), 'cluster-manifest.yaml')


def mkdirs(project_dir: str) -> str:
    if not os.path.isdir(project_dir):
        os.makedirs(project_dir, exist_ok=True)
        logging.info("Created directory: " + project_dir)

    return project_dir

