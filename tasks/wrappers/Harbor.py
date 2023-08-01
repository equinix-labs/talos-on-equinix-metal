import harbor_client
from harbor_client import Configuration

from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster


class Harbor:
    _client_config: Configuration
    _context: SystemContext
    _cluster: Cluster

    def __init__(self, context: SystemContext, cluster: Cluster = None):
        self._client_config = harbor_client.Configuration()
        self._context = context
        self._cluster = context.cluster()
        if cluster is not None:
            self._cluster = cluster

        self._client_config.host = "https://{}/api/v2.0".format(
            get_fqdn(
                ['harbor', self._cluster.name],
                context.secrets,
                self._cluster
            ))
        self._client_config.username = context.secrets['harbor']['admin_user']
        self._client_config.password = context.secrets['harbor']['admin_pass']

    def oidc_enable(self):
        config_api = harbor_client.ConfigureApi(harbor_client.ApiClient(self._client_config))
        config = harbor_client.Configurations()

        config.oidc_client_secret = self._context.secrets['harbor']['dex_client_secret']
        config.auth_mode = 'oidc_auth'
        config.oidc_admin_group = self._context.secrets['harbor']['oidc_admin_group']
        config.oidc_auto_onboard = True
        config.oidc_client_id = 'harbor'
        config.oidc_endpoint = "https://{}".format(get_fqdn('bouncer', self._context.secrets, self._cluster))
        config.oidc_groups_claim = 'groups'
        config.oidc_name = 'dex'
        config.oidc_scope = 'openid,email,groups,profile,offline_access'
        config.oidc_user_claim = 'email'
        config.oidc_verify_cert = True

        config.project_creation_restriction = 'adminonly'

        config_api.update_configurations(config)
