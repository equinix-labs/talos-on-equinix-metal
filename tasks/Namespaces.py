from enum import Enum


class Namespace(Enum):
    argocd = 'argocd'
    capi = 'capi'
    dns_tls = 'dns-tls'

    def __str__(self):
        return self.value
