import logging

from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.Namespaces import Namespace


class CockroachDB:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            application_directory: str = 'dbs'):

        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._application_directory = application_directory

    def install(self, install: bool, ingress_enabled: bool = False):
        """
        We are installing CockroachDB on satellite clusters only. This can be easily changed.
        """
        first_cluster = None
        secrets = self._context.secrets
        context = self._context.cluster()

        for cluster in self._context.constellation.satellites:
            if first_cluster is None:
                first_cluster = cluster

            data = {
                'values': {
                    'cluster_domain': cluster.name + '.local',
                    'cluster_name': self._context.constellation.name,
                    'locality': cluster.name,
                    'cockroach_fqdn': get_fqdn('cockroach', secrets, cluster),
                    'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
                    'ca_issuer_name': "{}-ca-issuer".format(self._context.constellation.name),
                    'first_cluster': first_cluster.name,
                    'ingress_enabled': ingress_enabled,
                    'replica_count': 3,
                    'empty_list': '[]' if first_cluster == cluster else ''
                }
            }
            data['values'].update(secrets['dbs'])

            self._context.set_cluster(cluster)
            ApplicationsCtrl(self._ctx, self._context, self._echo, cluster=cluster).install_app(
                self._application_directory, data, Namespace.database, install)

        self._context.set_cluster(context)

    def uninstall(self):
        context = self._context.cluster()
        for cluster in self._context.constellation.satellites:
            self._context.set_cluster(cluster)
            try:
                self._ctx.run(
                    "helm --namespace {} uninstall {}".format(Namespace.database, self._application_directory),
                    echo=self._echo)
            except Failure:
                logging.info("Already gone...")

            self._ctx.run("kubectl --namespace {} delete pvc --all".format(Namespace.database),
                          echo=self._echo)

            self._ctx.run("kubectl --namespace {} delete pods --all".format(Namespace.database),
                          echo=self._echo)

        self._context.set_cluster(context)

    def port_forward(self, cluster_nme: str):
        cluster = self._context.cluster(cluster_nme)
        index = self._context.constellation.satellites.index(cluster)

        self._ctx.run("kubectl --context admin@{} --namespace {} port-forward dbs-cockroachdb-0 808{}:8080".format(
            cluster.name,
            Namespace.database,
            index
        ), echo=self._echo)
