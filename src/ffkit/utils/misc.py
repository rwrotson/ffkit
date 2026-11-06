from pathlib import Path


def find_project_root(marker: str = "pyproject.toml") -> Path:
    """Find the project root by searching upwards for a marker."""
    current_path = Path(__file__).resolve()
    while current_path != current_path.parent:
        if (current_path / marker).exists():
            return current_path
        current_path = current_path.parent

    return Path(__file__).parent.resolve()
