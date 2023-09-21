from invoke import Context

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.Namespaces import Namespace


class Observability:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool):
        """
        https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._namespace = Namespace.observability

    def install(self, install: bool, application_directory: str = 'observability'):
        master_cluster = self._context.constellation.bary

        initial_cluster = self._context.cluster()
        application_directory = 'observability'
        secrets = self._context.secrets

        for cluster in self._context.constellation:
            self._context.set_cluster(cluster)

            data = {
                'values': {
                    'jaeger_fqdn': get_fqdn('jaeger', secrets, cluster),
                    'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
                    'grafana_fqdn': get_fqdn('grafana', secrets, cluster),
                    'cluster_name': cluster.name + '.local'
                }
            }
            data['values'].update(secrets['grafana'])

            ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
                application_directory, data, Namespace.observability, install, '{}-{}'.format(
                    application_directory, cluster.name
                ))

        self._context.set_cluster(initial_cluster)