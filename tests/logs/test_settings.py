import pytest
from pydantic import ValidationError

from ffkit.logs import LogSettings


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../outside.log", "sub/log", "..\\outside.log", "/outside.log"],
)
def test_log_file_name_must_be_basename(name: str) -> None:
    with pytest.raises(ValidationError, match="basename"):
        LogSettings(file_name=name)
