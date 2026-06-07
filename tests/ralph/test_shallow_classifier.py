from cccc.ralph.shallow_check_classifier import is_shallow_check


def test_shallow_import_check() -> None:
    assert is_shallow_check("import_check", "") is True


def test_shallow_compile_check() -> None:
    assert is_shallow_check("compile_check", "") is True


def test_behavioral_test_check() -> None:
    assert is_shallow_check("test_endpoint", "") is False


def test_behavioral_pytest_command() -> None:
    assert is_shallow_check("check", "pytest test_foo.py") is False


def test_mixed_shallow_behavioral() -> None:
    assert is_shallow_check("import_test", "") is False
