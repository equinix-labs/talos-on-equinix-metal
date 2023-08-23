import logging

from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.Namespaces import Namespace


class JFrog:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            application_directory: str = 'jfrog'):
        """
        https://github.com/devopshq/artifactory
        https://jfrog.com/help/r/jfrog-installation-setup-documentation/install-artifactory-ha-with-helm
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._application_directory = application_directory

    def _create_namespace(self):
        try:
            self._ctx.run("kubectl create namespace {}".format(Namespace.jfrog), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def _create_db_config(self):
        """
        For some reason Artifactory helm chart fails to create access secrets for external DB
        """
        try:
            self._ctx.run("kubectl --namespace {} create secret generic {} --from-literal={}={}".format(
                Namespace.jfrog,
                self._context.secrets['jfrog']['artifactory']['db_user'],
                self._context.secrets['jfrog']['artifactory']['db_user'],
                self._context.secrets['jfrog']['artifactory']['db_pass']
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

        try:
            self._ctx.run("kubectl --namespace {} create secret generic {} --from-literal={}={}".format(
                Namespace.jfrog,
                'artifactory-database-creds',
                'db-url',
                "'jdbc:postgresql://dbs-cockroachdb-public.dbs:26257/artifactory?sslmode=disable&user={}'".format(
                    self._context.secrets['jfrog']['artifactory']['db_user'])
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def install(self, install: bool):
        context = self._context.cluster()
        for cluster in self._context.constellation.satellites:
            self._context.set_cluster(cluster)
            self._create_namespace()
            self._create_db_config()
            data = {
                'values': {},
                'deps': {
                    '10_important_stuff': {
                        'pvc_name': 'artifactory-data-volume'
                    },
                    '20_artifactory': {
                        'fqdn': get_fqdn('artifactory', self._context.secrets, cluster),
                        'artifactory': self._context.secrets['jfrog']['artifactory']
                    }
                }
            }
            ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
                self._application_directory, data, Namespace.jfrog, install)

        self._context.set_cluster(context)

    def uninstall(self):
        try:
            self._ctx.run("helm uninstall --namespace {} {}".format(Namespace.jfrog, 'artifactory'), echo=self._echo)
        except Failure:
            logging.info('Most likely already gone...')
