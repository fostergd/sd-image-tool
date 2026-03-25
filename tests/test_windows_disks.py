import json

from sdtool.windows_disks import (
    _normalize_drive_letters,
    _normalize_drive_root,
    _parse_and_map_disks,
)


def test_normalize_drive_root_handles_common_windows_forms() -> None:
    assert _normalize_drive_root("c:\\vault-images\\test.img") == "C:"
    assert _normalize_drive_root("D:/tools/app.exe") == "D:"
    assert _normalize_drive_root("e:") == "E:"
    assert _normalize_drive_root("") is None
    assert _normalize_drive_root(None) is None


def test_normalize_drive_letters_handles_single_and_list_values() -> None:
    assert _normalize_drive_letters("f:\\") == {"F:"}
    assert _normalize_drive_letters(["g:", "H:\\mount", None, ""]) == {"G:", "H:"}
    assert _normalize_drive_letters(None) == set()


def test_parse_and_map_disks_includes_valid_usb_disk() -> None:
    json_output = json.dumps(
        [
            {
                "Number": 2,
                "FriendlyName": "USB SD Reader",
                "Size": 64 * 1024**3,
                "BusType": "USB",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": True,
                "DriveLetters": ["F:\\"],
            }
        ]
    )

    devices = _parse_and_map_disks(json_output, "C:")

    assert len(devices) == 1
    assert devices[0].device_id == r"\\.\PHYSICALDRIVE2"
    assert devices[0].display_name.startswith("USB SD Reader")
    assert devices[0].size_gb == 64
    assert devices[0].removable is True


def test_parse_and_map_disks_includes_scsi_card_reader() -> None:
    json_output = json.dumps(
        [
            {
                "Number": 4,
                "FriendlyName": "Realtek PCIE CardReader",
                "Size": 32 * 1024**3,
                "BusType": "SCSI",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": False,
                "DriveLetters": [],
            }
        ]
    )

    devices = _parse_and_map_disks(json_output, "C:")

    assert len(devices) == 1
    assert devices[0].device_id == r"\\.\PHYSICALDRIVE4"
    assert devices[0].display_name.startswith("Realtek PCIE CardReader")
    assert devices[0].size_gb == 32


def test_parse_and_map_disks_excludes_tool_drive() -> None:
    json_output = json.dumps(
        [
            {
                "Number": 3,
                "FriendlyName": "Portable SSD",
                "Size": 256 * 1024**3,
                "BusType": "USB",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": True,
                "DriveLetters": ["C:\\"],
            }
        ]
    )

    devices = _parse_and_map_disks(json_output, "C:")

    assert devices == []


def test_parse_and_map_disks_excludes_non_removable_internal_disk() -> None:
    json_output = json.dumps(
        [
            {
                "Number": 1,
                "FriendlyName": "Internal NVMe",
                "Size": 512 * 1024**3,
                "BusType": "NVMe",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": False,
                "DriveLetters": ["D:\\"],
            }
        ]
    )

    devices = _parse_and_map_disks(json_output, "C:")

    assert devices == []


def test_parse_and_map_disks_invalid_json_returns_empty_list() -> None:
    assert _parse_and_map_disks("not valid json", "C:") == []


def test_parse_and_map_disks_skips_bad_record_but_keeps_good_one() -> None:
    json_output = json.dumps(
        [
            {
                "Number": 5,
                "FriendlyName": "Good USB Disk",
                "Size": 32 * 1024**3,
                "BusType": "USB",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": True,
                "DriveLetters": ["G:\\"],
            },
            {
                "FriendlyName": "Bad Disk Missing Number",
                "BusType": "USB",
                "IsSystem": False,
                "IsBoot": False,
                "IsRemovable": True,
                "DriveLetters": ["H:\\"],
            },
        ]
    )

    devices = _parse_and_map_disks(json_output, "C:")

    assert len(devices) == 1
    assert devices[0].device_id == r"\\.\PHYSICALDRIVE5"
