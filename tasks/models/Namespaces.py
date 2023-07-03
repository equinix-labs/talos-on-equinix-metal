from enum import Enum


class Namespace(Enum):
    argocd = 'argocd'
    capi = 'capi'
    dns_tls = 'dns-tls'
    network_services = 'network-services'

    def __str__(self):
        return self.value
