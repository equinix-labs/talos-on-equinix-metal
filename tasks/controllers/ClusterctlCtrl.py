from tasks.dao.LocalStateCtrl import LocalStateCtrl
from tasks.helpers import user_confirmed
from tasks.models.ConstellationSpecV01 import Constellation, Cluster


def clusterctl_init(ctx, constellation: Constellation, cluster: Cluster, echo=False):
    """
    Run clusterctl init with predefined providers
    """

    if cluster.name == constellation.bary.name:
        if user_confirmed('Is cert-manager present ? - did you run "invoke apps.install-dns-and-tls-dependencies"'):
            return

    ctx.run("clusterctl init "
            "--core=cluster-api:{} "
            "--bootstrap=talos:{} "
            "--control-plane=talos:{} "
            "--infrastructure=packet:{}".format(
                    constellation.capi,
                    constellation.cabpt,
                    constellation.cacppt,
                    constellation.capp
                ), echo=echo)


def kind_create(ctx, local_state_ctrl: LocalStateCtrl, echo=False):
    """
    Create local kind k8s cluster and initialise clusterctl
    """

    ctx.run("kind create cluster --name {}".format(local_state_ctrl.cluster.name), echo=echo)
    clusterctl_init(ctx, local_state_ctrl.constellation, local_state_ctrl.cluster, echo)
