import yaml
from invoke import task

from tasks.dao.SystemContext import SystemContext
from tasks.helpers import str_presenter, get_cluster_spec_from_context
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Cilium import Cilium

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


@task()
def apply_kubespan_patch(ctx):
    """
    For some reason, Kubespan turns off once cilium is deployed.
    https://www.talos.dev/v1.4/kubernetes-guides/network/kubespan/
    Once the patch is applied kubespan is back up.
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    ctx.run("talosctl --context {} patch mc -p @patch-templates/kubespan/common.pt.yaml".format(
        cluster_spec.name
    ), echo=True)


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
