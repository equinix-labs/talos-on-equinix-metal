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

    def install(self, install: bool):
        data = {
            'values': {},
            'deps': {
                'artifactory': {
                    'fqdn': get_fqdn('artifactory', self._context.secrets, self._context.cluster()),
                    'artifactory': self._context.secrets['jfrog']['artifactory']
                }
            }
        }
        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            self._application_directory, data, Namespace.jfrog, install)

    def uninstall(self):
        try:
            self._ctx.run("helm uninstall --namespace {} {}".format(Namespace.jfrog, 'artifactory'), echo=self._echo)
        except Failure:
            logging.info('Most likely already gone...')
