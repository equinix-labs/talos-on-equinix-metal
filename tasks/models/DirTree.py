import os.path

from tasks.models.ConstellationSpecV01 import Cluster, Constellation


class DirTree:
    _root: str  # default config root dir
    _repo: bool = False
    _ca: str = "ca"
    _constellation: Constellation = None
    _cluster: Cluster = None
    _cluster_k8s_manifests = "k8s_manifests"
    _cluster_templates = "templates"
    _cluster_patch = "patch"
    _cluster_apps = "apps"
    _cluster_argo_apps = os.path.join("argo", "apps")
    _cluster_argo_infra = os.path.join("argo", "infra")
    _cluster_talos = "talos"
    _cluster_access = "access"

    def __init__(
            self,
            root: str = None,
            constellation: Constellation = None,
            cluster: Cluster = None,
            repo: bool = False
    ):
        if root is not None:
            self._root = root
        else:
            self._root = os.environ.get('GOCY_ROOT', '.gocy')

        self._repo = repo
        if constellation is not None:
            self._constellation = constellation

        if cluster is not None:
            self._cluster = cluster

    def _project_root(self):
        if self._repo:
            self._constellation = Constellation(name='')
            return os.getcwd()

        if os.path.isabs(self._root):
            root_dir = self._root
        else:
            root_dir = os.path.join(os.path.expanduser('~'), self._root)

        return root_dir

    def _constellation_root(self):
        return os.path.join(self._project_root(), self._constellation.name)
    
    def _cluster_root(self, cluster: Cluster = None):
        if cluster is None:
            return self._constellation_root()

        if cluster in self._constellation:
            return os.path.join(
                self._constellation_root(),
                cluster.name
            )
        else:
            raise Exception("Cluster {} not part of constellation {}".format(cluster.name, self._constellation.name))

    def root(self, path: list = None):
        """
        gocy root directory
        """
        if path is None:
            path = []

        return os.path.join(self._project_root(), *path)

    def ca(self, path: list = None):
        """
        Certificate Authority root directory
        """
        if path is None:
            path = []

        return os.path.join(self._project_root(), self._ca, *path)

    def constellation(self, path: list = None):
        """
        constellation root directory
        """
        if path is None:
            path = []

        return os.path.join(self._constellation_root(), *path)

    def cluster(self, cluster: Cluster = None, path: list = None):
        """
        constellation cluster root directory
        """
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), *path)

    def k8s_manifests(self, cluster: Cluster = None, path: list = None):
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_k8s_manifests, *path)

    def patch(self, cluster: Cluster = None, path: list = None):
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_patch, *path)

    def apps(self, cluster: Cluster = None, path: list = None):
        """
        Application specs are grouped here
        """
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_apps, *path)

    def argo_apps(self, cluster: Cluster = None, path: list = None):
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_argo_apps, *path)

    def argo_infra(self, cluster: Cluster = None, path: list = None):
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_argo_infra, *path)

    def templates(self, cluster: Cluster = None, path: list = None):
        if path is None:
            path = []

        return os.path.join(self._cluster_root(cluster), self._cluster_templates, *path)

    def talos(self, cluster: Cluster = None):
        return os.path.join(self._cluster_root(cluster), self._cluster_talos)

    def access(self, cluster: Cluster = None):
        return os.path.join(self._cluster_root(cluster), self._cluster_access)
