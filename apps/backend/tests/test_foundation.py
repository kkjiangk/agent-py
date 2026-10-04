from super_ai import FoundationInfo, get_foundation_info


def test_backend_foundation_imports_by_package_name() -> None:
    info = get_foundation_info()

    assert isinstance(info, FoundationInfo)
    assert info.service == "super-ai-backend"
    assert info.status == "ok"
    assert info.version == "0.1.0"
