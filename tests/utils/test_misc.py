from pathlib import Path

import ffkit.utils.misc as _misc_module
from ffkit.utils.misc import find_project_root


def test_find_project_root_contains_pyproject_toml() -> None:
    root = find_project_root()
    assert (root / "pyproject.toml").exists()


def test_find_project_root_unknown_marker_falls_back_to_module_parent() -> None:
    # When no ancestor has the marker the function returns Path(__file__).parent.
    assert _misc_module.__file__ is not None
    expected = Path(_misc_module.__file__).parent.resolve()
    result = find_project_root(marker="_nonexistent_marker_xyz_")
    assert result == expected
