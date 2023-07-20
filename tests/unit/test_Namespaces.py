from tasks.models.Namespaces import Namespace


def test_get_namespace_by_key():
    namespace = Namespace['nginx']
    assert namespace.value == 'nginx'
