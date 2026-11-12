import pytest
from pydantic import ValidationError

from ffkit.audio import Mp3Encoding


def test_mp3_encoding_arguments() -> None:
    assert Mp3Encoding().codec_args() == ["-codec:a", "libmp3lame", "-b:a", "320k"]
    assert Mp3Encoding(bitrate_kbps=128).codec_args()[-1] == "128k"
    assert Mp3Encoding(vbr_quality=2).codec_args() == ["-codec:a", "libmp3lame", "-q:a", "2"]
    assert Mp3Encoding().extension == ".mp3"
    assert Mp3Encoding().muxer == "mp3"


@pytest.mark.parametrize(
    "value", [{"bitrate_kbps": 16}, {"bitrate_kbps": 321}, {"vbr_quality": 10}]
)
def test_mp3_encoding_rejects_invalid_values(value: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Mp3Encoding.model_validate(value)
