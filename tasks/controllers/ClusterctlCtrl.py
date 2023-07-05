from tasks.dao.LocalState import LocalState
from tasks.helpers import user_confirmed
from tasks.models.Defaults import KIND_CLUSTER_NAME


class ClusterctlCtrl:

    _state: LocalState

    def __init__(self, state: LocalState, echo: bool = False):
        self._state = state
        self._echo = echo

    def init(self, ctx):
        """
        Run clusterctl init with predefined providers
        """

        if self._state.cluster.name == self._state.constellation.bary.name:
            if user_confirmed('Is cert-manager present ? - did you run "invoke apps.install-dns-and-tls-dependencies"'):
                return

        ctx.run("clusterctl init "
                "--core=cluster-api:{} "
                "--bootstrap=talos:{} "
                "--control-plane=talos:{} "
                "--infrastructure=packet:{}".format(
                        self._state.constellation.capi,
                        self._state.constellation.cabpt,
                        self._state.constellation.cacppt,
                        self._state.constellation.capp
                    ), echo=self._echo)

    def kind_create(self, ctx):
        """
        Create local kind k8s cluster and initialise clusterctl
        """
        kind_clusters = ctx.run("kind get clusters", hide='stdout', echo=self._echo).stdout.splitlines()
        for kind_cluster in kind_clusters:
            if kind_cluster == KIND_CLUSTER_NAME:
                kind_delete(ctx, self._echo)

        ctx.run("kind create cluster --name {}".format(KIND_CLUSTER_NAME), echo=self._echo)
        self.init(ctx)


def kind_delete(ctx, echo=False):
    if user_confirmed("Delete kind cluster {} ?".format(KIND_CLUSTER_NAME)):
        ctx.run("kind delete cluster --name {}".format(KIND_CLUSTER_NAME), echo=echo)
