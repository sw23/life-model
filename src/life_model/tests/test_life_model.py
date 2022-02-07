import life_model


def test_project_defines_author_and_version():
    assert hasattr(life_model, '__author__')
    assert hasattr(life_model, '__version__')
