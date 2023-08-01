import yaml
from invoke import task

from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Cilium import Cilium

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def connect(ctx, echo: bool = False):
    """
    Connects constellation clusters
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    cilium = Cilium(ctx, state, echo)
    cilium.cluster_mesh_connect()


@task()
def disconnect(ctx, echo: bool = False):
    """
    Disconnects constellation clusters
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    cilium = Cilium(ctx, state, echo)
    cilium.cluster_mesh_disconnect()


@task()
def status(ctx, echo: bool = False):
    """
    Cilium status
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    cilium = Cilium(ctx, state, echo)
    cilium.status()


@task()
def status_mesh(ctx, echo: bool = False):
    """
    Cilium ClusterMesh status
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    cilium = Cilium(ctx, state, echo)
    cilium.cluster_mesh_status()


@task()
def restart(ctx, echo: bool = False, namespace: Namespace = Namespace.network_services):
    """
    Cilium ClusterMesh status
    https://docs.cilium.io/en/v1.13/network/clustermesh/clustermesh/#enable-cluster-mesh
    """
    state = SystemContext(ctx, echo)
    cilium = Cilium(ctx, state, echo)
    cilium.restart(namespace)
