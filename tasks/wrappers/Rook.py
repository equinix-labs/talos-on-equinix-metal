from invoke import Context

from tasks.dao.SystemContext import SystemContext
from tasks.models.Namespaces import Namespace


class Rook:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False):
        """

        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._namespace = Namespace.storage

    def status_osd(self):
        self._ctx.run("kubectl rook-ceph --namespace {} ceph osd status".format(self._namespace), echo=self._echo)