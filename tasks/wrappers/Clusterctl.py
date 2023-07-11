from tasks.dao.SystemContext import SystemContext
from tasks.helpers import user_confirmed
from tasks.models.Defaults import KIND_CLUSTER_NAME


class Clusterctl:

    _context: SystemContext

    def __init__(self, context: SystemContext, echo: bool = False):
        self._context = context
        self._echo = echo

    def init(self, ctx):
        """
        Run clusterctl init with predefined providers
        """

        # if self._context.cluster.name == self._context.constellation.bary.name:
        #     if user_confirmed('Is cert-manager present ? - did you run "invoke apps.install-dns-and-tls-dependencies"'):
        #         return

        ctx.run("clusterctl init "
                "--core=cluster-api:{} "
                "--bootstrap=talos:{} "
                "--control-plane=talos:{} "
                "--infrastructure=packet:{}".format(
                        self._context.constellation.capi,
                        self._context.constellation.cabpt,
                        self._context.constellation.cacppt,
                        self._context.constellation.capp
                    ), echo=self._echo)

    def kind_create(self, ctx):
        """
        Create local kind k8s cluster and initialise clusterctl
        """
        kind_clusters = ctx.run("kind get clusters", hide='stdout', echo=self._echo).stdout.splitlines()
        cluster_exists = False
        for kind_cluster in kind_clusters:
            if kind_cluster == KIND_CLUSTER_NAME:
                cluster_exists = not kind_delete(ctx, self._echo)

        if not cluster_exists:
            ctx.run("kind create cluster --name {}".format(KIND_CLUSTER_NAME), echo=self._echo)

        self.init(ctx)


def kind_delete(ctx, echo=False) -> bool:
    if user_confirmed("Delete kind cluster {} ?".format(KIND_CLUSTER_NAME)):
        ctx.run("kind delete cluster --name {}".format(KIND_CLUSTER_NAME), echo=echo)
        return True

    return False
