import logging
import os.path
from enum import Enum

from invoke import Context, Failure

from tasks.dao.SystemContext import SystemContext
from tasks.models.Namespaces import Namespace


class DNSProvider(Enum):
    gcp = 'gcp'
    aws = 'aws'

    def __str__(self):
        return self.value


class DNSCtrl:

    _state: SystemContext
    _ctx: Context
    _echo: bool

    def __init__(self, ctx: Context, state: SystemContext, echo: bool):
        self._ctx = ctx
        self._state = state
        self._echo = echo

    def _gcp_get_admin_token(self):
        token_file_path = self._state.project_paths.gcp_token_file()
        if os.path.isfile(token_file_path):
            print("File {} already exists, skipping".format(token_file_path))
            return

        secrets = self._state.secrets

        self._ctx.run("gcloud iam service-accounts keys create {} --iam-account {}@{}.iam.gserviceaccount.com".format(
            self._state.project_paths.gcp_token_file(),
            secrets['env']['GCP_SA_NAME'],
            secrets['env']['GCP_PROJECT_ID']
        ), echo=self._echo)

    def _create_secret_gcp(self):
        try:
            self._ctx.run(
                'kubectl create namespace {}'.format(Namespace.dns_tls),
                echo=self._echo
            )
        except Failure:
            logging.info("Namespace already exists")

        self._ctx.run("kubectl -n {} create secret generic '{}' --from-file=credentials.json={} | true".format(
            Namespace.dns_tls,
            self._state.secrets['env']['GCP_SA_NAME'],
            self._state.project_paths.gcp_token_file()
        ), echo=self._echo)

    def create_secret(self, provider: DNSProvider):
        """
        Expects user issued: 'gcloud auth login'
        """
        if provider == DNSProvider.gcp:
            self._gcp_get_admin_token()
            self._create_secret_gcp()
        else:
            logging.fatal("Unrecognised provider: {}".format(provider))
