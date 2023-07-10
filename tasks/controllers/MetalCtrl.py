import json

import yaml

from tasks.dao.SystemContext import SystemContext
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.helpers import str_presenter
from tasks.models.ConstellationSpecV01 import Cluster, VipRole, VipType, Vip, Constellation
from tasks.models.ReservedVIPs import ReservedVIPs

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


class MetalCtrl:
    state: SystemContext
    constellation: Constellation
    ppaths: ProjectPaths
    echo: bool

    def __init__(self, state: SystemContext, echo: bool):
        self.state = state
        self.constellation = state.constellation
        self.echo = echo
        self.ppaths = state.project_paths

    def register_vips(self, ctx):
        """
        Registers VIPs as per constellation spec in ~/.gocy/[constellation_name].constellation.yaml
        """
        
        project_vips_file_path = self.ppaths.project_vips_file()
        ctx.run("metal ip get -o yaml > {}".format(project_vips_file_path), echo=self.echo)

        with open(project_vips_file_path) as project_vips_file:
            project_vips = list(yaml.safe_load(project_vips_file))

        global_vip = None
        for cluster in self.constellation:
            for vip_spec in cluster.vips:
                vip_tags = get_vip_tags(vip_spec.role, cluster)
                for project_vip in project_vips:
                    if 'tags' in project_vip:
                        if project_vip['type'] == vip_spec.vipType and vip_spec.vipType == VipType.global_ipv4:
                            if self.is_constellation_member(project_vip.get('tags')) and vip_role_match(
                                    vip_spec.role, project_vip.get('tags')):
                                if global_vip is None:
                                    global_vip = project_vip
                                    vip_spec.reserved.append(project_vip)
                                else:
                                    vip_spec.reserved.append(global_vip)

                        if project_vip['type'] == vip_spec.vipType and vip_spec.vipType == VipType.public_ipv4:
                            if project_vip.get('tags') == vip_tags \
                                    and 'metro' in project_vip and project_vip['metro']['code'] == cluster.metro:
                                vip_spec.reserved.append(project_vip)

            for vip_spec in cluster.vips:
                vip_tags = get_vip_tags(vip_spec.role, cluster)
                if len(vip_spec.reserved) == 0:
                    # Register missing VIPs
                    if vip_spec.vipType == VipType.public_ipv4:
                        vip_spec.reserved.extend(
                            register_public_vip(ctx, cluster, vip_spec, vip_tags)
                        )
                    else:
                        if global_vip is None:
                            global_vip = register_global_vip(ctx, vip_spec, vip_tags)

                        vip_spec.reserved.extend(global_vip)

            self.render_vip_addresses_file(cluster)

    def render_vip_addresses_file(self, cluster: Cluster):
        data = {
            VipRole.cp: ReservedVIPs(),
            VipRole.mesh: ReservedVIPs(),
            VipRole.ingress: ReservedVIPs()
        }

        for vip in cluster.vips:
            data[vip.role].extend(vip.reserved)
            paths = ProjectPaths(self.state.constellation.name, cluster.name)
            with open(paths.vips_file_by_role(vip.role), 'w') as ip_addresses_file:
                ip_addresses_file.write(data[vip.role].yaml())

    def get_vips(self, vip_role: VipRole) -> ReservedVIPs:
        with open(self.ppaths.vips_file_by_role(vip_role)) as cp_address:
            return ReservedVIPs.parse_raw(cp_address.read())

    # def get_cp_vip_address(cluster_spec):
    #     return get_vips(cluster_spec, VipRole.cp).public_ipv4[0]

    def is_constellation_member(self, tags: list) -> bool:
        cluster_name_from_tag = tags[0].split(":")[-1:][0]  # First tag, last field, delimited by :
        if type(cluster_name_from_tag) is not str:
            print("Tags: {} are not what was expected".format(tags))

        if Cluster(name=cluster_name_from_tag) in self.constellation:
            return True

        return False


def register_public_vip(ctx, cluster: Cluster, vip: Vip, tags: list):
    result = ctx.run("metal ip request --type {} --quantity {} --metro {} --tags '{}' -o yaml".format(
        VipType.public_ipv4,
        vip.count,
        cluster.metro,
        ",".join(tags)
    ), hide='stdout', echo=True).stdout
    if vip.count > 1:
        return [dict(yaml.safe_load(result))]
    else:
        return list(yaml.safe_load_all(result))


def register_global_vip(ctx, vip: Vip, tags: list):
    """
    We want to ensure that only one global_ipv4 is registered for all satellites. Following behaviour should not
    affect the management cluster (bary).

    ToDo:
        There is a bug in Metal CLI that prevents us from using the CLI in this case.
        Thankfully API endpoint works.
        https://deploy.equinix.com/developers/docs/metal/networking/global-anycast-ips/
    """
    payload = {
        "type": VipType.global_ipv4,
        "quantity": vip.count,
        "fail_on_approval_required": "true",
        "tags": tags
    }
    result = ctx.run("curl -s -X POST "
                     "-H 'Content-Type: application/json' "
                     "-H \"X-Auth-Token: {}\" "
                     "\"https://api.equinix.com/metal/v1/projects/{}/ips\" "
                     "-d '{}'".format(
                            "${METAL_AUTH_TOKEN}",
                            "${METAL_PROJECT_ID}",
                            json.dumps(payload)
                        ), hide='stdout', echo=True).stdout

    if vip.count > 1:
        return [dict(yaml.safe_load(result))]
    else:
        return list(yaml.safe_load_all(result))


def get_vip_tags(address_role: VipRole, cluster: Cluster) -> list:
    """
    ToDo: Despite all the efforts to disable it
        https://github.com/kubernetes-sigs/cluster-api-provider-packet on its own registers a VIP for the control plane.
        We need one so we will use it. The tag remains defined by CAPP.
        As for the tags the 'cp' VIP is used for the Control Plane. The 'ingress' VIP will be used by the ingress.
        The 'mesh' VIP will be used by cilium as ClusterMesh endpoint.
    """
    if address_role == VipRole.cp:
        return ["cluster-api-provider-packet:cluster-id:{}".format(cluster.name)]
    else:
        return ["gocy:cluster:{}".format(cluster.name), "gocy:vip:{}".format(address_role.name)]


def vip_role_match(vip_role: VipRole, tags: list) -> bool:
    if len(tags) == 1:
        if vip_role == VipRole.cp:
            return True
    elif len(tags) > 1:
        role_from_tag = tags[1].split(":")[-1:][0]  # Second tag, last field, delimited by :
        if role_from_tag == vip_role:
            return True

    return False

