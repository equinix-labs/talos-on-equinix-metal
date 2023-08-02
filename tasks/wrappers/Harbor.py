from typing import Callable

import harbor_client
from harbor_client import Configuration, ProjectReq

from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster


def _create_project(client_config: Configuration, cluster: Cluster, **kwargs):
    project_api = harbor_client.ProjectApi(harbor_client.ApiClient(client_config))
    project_req = ProjectReq()
    project_req.project_name = kwargs['project_name']
    project_req.public = False
    project_api.create_project(project_req)


class Harbor:
    _context: SystemContext
    _satellites: list[Cluster]

    def __init__(self, context: SystemContext, cluster: Cluster = None):
        self._context = context
        self._satellites = context.constellation.satellites
        if cluster is not None:
            self._satellites = [cluster]
        
    def _for_client_config(self, action: Callable, **kwargs):
        client_config = harbor_client.Configuration()
        client_config.username = self._context.secrets['harbor']['admin_user']
        client_config.password = self._context.secrets['harbor']['admin_pass']
        for cluster in self._satellites:
            client_config.host = "https://{}/api/v2.0".format(
                get_fqdn(
                    ['harbor', cluster.name],
                    self._context.secrets,
                    cluster
                ))
            action(client_config, cluster, **kwargs)

    def _oidc_enable(self, client_config: Configuration, cluster: Cluster):
        """
        OAUTH becomes the default auth mode.
        Login via DB possible via /account/sign-in
        """
        config_api = harbor_client.ConfigureApi(harbor_client.ApiClient(client_config))
        config = harbor_client.Configurations()

        print(config)

        config.oidc_client_secret = self._context.secrets['harbor']['dex_client_secret']
        config.auth_mode = 'oidc_auth'
        # config.primary_auth_mode = True
        config.oidc_admin_group = self._context.secrets['harbor']['oidc_admin_group']
        config.oidc_auto_onboard = True
        config.oidc_client_id = 'harbor'
        config.oidc_endpoint = "https://{}".format(get_fqdn('bouncer', self._context.secrets, cluster))
        config.oidc_groups_claim = 'groups'
        config.oidc_name = 'dex'
        config.oidc_scope = 'openid,email,groups,profile,offline_access'
        config.oidc_user_claim = 'email'
        config.oidc_verify_cert = True

        config.project_creation_restriction = 'adminonly'

        config_api.update_configurations(config)

    def oidc_enable(self):
        self._for_client_config(self._oidc_enable)

    def create_project(self, project_name: str):
        self._for_client_config(_create_project, project_name=project_name)
