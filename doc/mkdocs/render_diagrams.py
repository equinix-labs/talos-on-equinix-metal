#!/usr/bin/env python

from diagrams import Diagram, Cluster
from diagrams.k8s.infra import Master, Node
from diagrams.k8s.network import Ingress
from diagrams.generic.os import Windows, LinuxGeneral
from diagrams.generic.network import VPN

with Diagram("Default deployment architecture", outformat="png",
             filename="docs/img/architecture", show=True,
             graph_attr={
                 'ratio': 'expand'}):
    with Cluster("Private cloud"):
        cm = Cluster("Management")
        with cm:
            with Cluster("Nodes"):
                with Cluster("Masters"):
                    cmMasters = [Master("M1"), Master("M2"), Master("M3")]
                with Cluster("Workers"):
                    cmNodes = [Node("N1"), Node("N2"), Node("N2")]
            with Cluster("apps"):
                cmIngress = Ingress("Ingress")
                cmVPN = VPN("Cilium Mesh, VPN")

        cs1 = Cluster("Site1")
        with cs1:
            with Cluster("Nodes"):
                with Cluster("Masters"):
                    cs1Masters = [Master("M1"), Master("M2"), Master("M3")]
                with Cluster("Workers"):
                    cs1Nodes = [Node("N1"), Node("N2"), Node("N2")]
            with Cluster("apps"):
                cs1Ingress = Ingress("Ingress")
                cs1VPN = VPN("Cilium Mesh, VPN")

        cs2 = Cluster("Site2")
        with cs2:
            with Cluster("Nodes"):
                with Cluster("Masters"):
                    cs2Masters = [Master("M1"), Master("M2"), Master("M3")]
                with Cluster("Workers"):
                    cs2Nodes = [Node("N1"), Node("N2"), Node("N2")]
            with Cluster("apps"):
                cs2Ingress = Ingress("Ingress")
                cs2VPN = VPN("Cilium Mesh, VPN")

    with Cluster("admins"):
        wAdmin = Windows('Windows admin')
        lAdmin = LinuxGeneral('Linux admin')

    with Cluster("Clients"):
        wClient = Windows('Windows client')
        lClient = LinuxGeneral('Linux client')

    cmVPN - cs1VPN - cs2VPN

    cmMasters - cmVPN
    cmNodes - cmVPN

    cs1Masters - cs1VPN
    cs1Nodes -cs1VPN

    cs2Masters -cs2VPN
    cs2Nodes - cs2VPN

    wAdmin >> cmIngress
    lAdmin >> cmIngress

    wClient >> cs1Ingress
    wClient >> cs2Ingress

    lClient >> cs2Ingress
    lClient >> cs2Ingress

