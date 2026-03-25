import pytest

from sdtool.backend import MockBackend, OperationContext


def test_mock_backend_returns_devices() -> None:
    backend = MockBackend()

    assert len(backend.list_source_devices()) >= 1
    assert len(backend.list_target_devices()) >= 1


def test_mock_backend_returns_steps_for_known_operation() -> None:
    backend = MockBackend()

    steps = backend.get_operation_steps("save")

    assert len(steps) == 4
    assert steps[0][0] == "Check source device"


def test_mock_backend_raises_for_unknown_operation() -> None:
    backend = MockBackend()

    with pytest.raises(ValueError):
        backend.get_operation_steps("not-a-real-operation")


def test_mock_backend_requires_image_path_for_write_related_operations() -> None:
    backend = MockBackend()

    warnings = backend.validate_operation(
        OperationContext(
            operation_name="write",
            source_device_id="PHYSICALDRIVE2",
            target_device_id="PHYSICALDRIVE4",
            image_path="",
        )
    )

    assert warnings
    assert "image path" in warnings[0].lower()


def test_mock_backend_blocks_same_source_and_target_device() -> None:
    backend = MockBackend()

    warnings = backend.validate_operation(
        OperationContext(
            operation_name="write",
            source_device_id="PHYSICALDRIVE2",
            target_device_id="PHYSICALDRIVE2",
            image_path="D:\\vault-images\\test.img",
        )
    )

    assert warnings
    assert "same" in warnings[0].lower()
