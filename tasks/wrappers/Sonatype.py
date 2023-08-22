import logging

from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.Namespaces import Namespace


class Sonatype:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            application_directory: str = 'sonatype'):
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
            self._ctx.run('kubectl create namespace {}'.format(
                Namespace.sonatype
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def _create_license_secret(self):
        try:
            self._ctx.run('kubectl --namespace {} create secret generic {} --from-file={}={}'.format(
                Namespace.sonatype,
                'nxrm-license',
                'nxrm-license.lic',
                self._context.project_paths.sonatype_license_file()
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def install(self, install: bool):
        self._create_namespace()
        self._create_license_secret()

        data = {
            'values': {
                'fqdn': get_fqdn('nexus', self._context.secrets, self._context.cluster()),
                'oauth_fqdn': get_fqdn('oauth', self._context.secrets, self._context.cluster()),
                'nexus': self._context.secrets['sonatype']['nexus'],
                'db_name': 'nexus'
            }
        }

        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            self._application_directory, data, Namespace.sonatype, install)
