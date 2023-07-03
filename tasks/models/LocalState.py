from pydantic_yaml import YamlModel

from tasks.models.Defaults import KIND_CLUSTER_NAME, CONSTELLATION_NAME


class LocalState(YamlModel):
    constellation_context: str = CONSTELLATION_NAME
    bary_cluster_context: str = KIND_CLUSTER_NAME
