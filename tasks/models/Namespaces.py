from enum import Enum


class Namespace(Enum):
    debug = 'debug'
    argocd = 'argocd'
    capi = 'capi'
    dns_tls = 'dns-tls'
    network_services = 'network-services'
    apps = 'apps'
    gitea = 'gitea'
    database = 'database'
    dashboards = 'dashboards'
    nginx = 'nginx'
    observability = 'observability'
    storage = 'storage'
    idp_auth = 'idp-auth'
    istio = 'istio-system'

    def __str__(self):
        return self.value
