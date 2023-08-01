import base64
import json

from tasks.helpers import get_cpem_config_yaml, get_cpem_config


def test_get_cpem_config_yaml():
    cpem_config = get_cpem_config_yaml()
    assert type(cpem_config) == str
    cpem_config_json = base64.b64decode(cpem_config)
    assert get_cpem_config() == json.loads(cpem_config_json)

