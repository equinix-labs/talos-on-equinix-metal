from tasks.helpers import get_config_dir


def test_get_config_dir(monkeypatch):
    config_dir = get_config_dir()
    assert config_dir is not None
    assert config_dir != ''

    monkeypatch.delenv('GOCY_DEFAULT_ROOT', raising=False)
    config_dir = get_config_dir()
    assert config_dir is not None
    assert config_dir != ''


