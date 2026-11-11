import array
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ffkit import (
    Track,
    analyze_peak_waveform,
    analyze_waveform_tempo,
    detect_trim_bounds,
    measure_loudness,
    probe,
    tempo_estimates,
)
from ffkit.core.audio import analysis


def make_tone(path: Path) -> None:
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-y",
            str(path),
        ],
        check=True,
    )


def test_probe_and_analysis_on_real_audio(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    track = probe(Track(path=str(source), tags={"title": "Custom"}))
    assert track.duration is not None
    assert 1.9 < track.duration < 2.1
    assert track.tags["title"] == "Custom"
    assert track.error is None
    assert len(analyze_peak_waveform(track)) == 400
    analyzed = analyze_waveform_tempo(track)
    assert analyzed is track
    assert analyzed.waveform
    assert len(analyzed.waveform_peak) == 400
    assert analyzed.waveform_peak[0] > 0
    lufs, peak = measure_loudness(source)
    assert lufs is not None
    assert peak is not None
    louder, _ = measure_loudness(source, ["volume=6dB"])
    assert louder is not None
    assert 5 < louder - lufs < 7
    assert detect_trim_bounds(source, track.duration) == (0.0, None)


def test_probe_reads_audio_stream_tags(tmp_path: Path) -> None:
    source = tmp_path / "stream-tags.mka"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:a",
            "flac",
            "-metadata:s:a:0",
            "title=Stream title",
            "-y",
            str(source),
        ],
        check=True,
    )
    assert probe(Track(path=str(source))).tags["title"] == "Stream title"


def test_probe_tag_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    report = {
        "streams": [{"codec_type": "audio", "tags": {"TITLE": "Stream", "ARTIST": "Singer"}}],
        "format": {"duration": "1", "tags": {"title": "Container", "album": "Album"}},
    }
    result = subprocess.CompletedProcess([], 0, stdout=json.dumps(report))
    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", lambda *args, **kwargs: result)
    tags = probe(Track(path=str(source), tags={"artist": "Custom"})).tags
    assert tags == {"title": "Stream", "artist": "Custom", "album": "Album"}


def test_reprobe_refreshes_source_tags_and_keeps_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    reports = iter(
        [
            {"title": "Old", "artist": "Artist", "album": "Old album"},
            {"title": "New", "artist": "New artist", "genre": "Rock"},
            {"title": "Latest", "artist": "Final artist"},
        ]
    )

    def fake_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        report = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "1", "tags": next(reports)},
        }
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(report))

    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", fake_probe)
    track = Track(path=str(source), tags={"artist": "Artist"})
    probe(track)
    assert track.tags == {"title": "Old", "artist": "Artist", "album": "Old album"}
    track.tags["genre"] = "Custom genre"
    probe(track)
    assert track.tags == {"title": "New", "artist": "Artist", "genre": "Custom genre"}
    del track.tags["artist"]
    track.tags["title"] = "Edited title"
    probe(track)
    assert track.tags == {
        "title": "Edited title",
        "artist": "Final artist",
        "genre": "Custom genre",
    }


def test_reprobe_after_json_round_trip_refreshes_source_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.wav"
    source.touch()
    titles = iter(("Old", "New"))

    def fake_probe(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        report = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "1", "tags": {"title": next(titles), "artist": "Source"}},
        }
        return subprocess.CompletedProcess([], 0, stdout=json.dumps(report))

    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", fake_probe)
    original = probe(Track(path=str(source), tags={"artist": "Custom"}))
    restored = Track.model_validate_json(original.model_dump_json())
    probe(restored)
    assert restored.tags == {"title": "New", "artist": "Custom"}


def test_peak_waveform_probes_missing_duration(tmp_path: Path) -> None:
    source = tmp_path / "delayed.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-af",
            "adelay=500|500",
            "-y",
            str(source),
        ],
        check=True,
    )
    peaks = analyze_peak_waveform(Track(path=str(source)))
    assert len(peaks) == 400
    assert 100 < next(index for index, peak in enumerate(peaks) if peak > 0) < 150


def test_decoded_chunks_timeout_includes_stdout_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis, "PROCESS_TIMEOUT", 0.01)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], stdout=subprocess.PIPE
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            list(analysis._decoded_chunks(process))
    finally:
        process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()


def test_probe_missing_and_bad_audio(tmp_path: Path) -> None:
    missing = probe(Track(path=str(tmp_path / "missing.wav")))
    assert missing.error == "Source file is missing"
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"invalid")
    with pytest.raises(subprocess.CalledProcessError):
        probe(Track(path=str(broken)))
    with pytest.raises(ValueError, match="duration"):
        detect_trim_bounds(broken, duration=0)


def test_trim_bounds_keep_internal_pause(tmp_path: Path) -> None:
    source = tmp_path / "edges.flac"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-filter_complex",
            "[0:a][1:a][0:a][1:a][0:a]concat=n=5:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )
    start, end = detect_trim_bounds(source)
    assert 0.9 < start < 1.1
    assert end is not None
    assert 3.9 < end < 4.1
    duration = probe(Track(path=str(source))).duration
    assert duration is not None
    assert detect_trim_bounds(source, duration) == (start, end)


def test_trim_bounds_preserve_short_audible_tail(tmp_path: Path) -> None:
    source = tmp_path / "short-tail.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=0.1:s=44100:d=0.05",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-y",
            str(source),
        ],
        check=True,
    )
    duration = probe(Track(path=str(source))).duration
    assert duration is not None
    assert detect_trim_bounds(source) == (0.0, None)
    assert detect_trim_bounds(source, duration) == (0.0, None)


def test_tempo_estimates_known_pulse_train() -> None:
    values = array.array("d", [1.0 if i % 5 == 0 else 0.0 for i in range(600)])
    estimates = tempo_estimates(memoryview(values))
    assert estimates
    assert estimates[0][1] == 120


def test_probe_rejects_missing_audio_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"x")
    result = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps({"streams": [{"codec_type": "video"}], "format": {}})
    )
    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", lambda *args, **kwargs: result)
    with pytest.raises(ValueError, match="no decodable audio"):
        probe(Track(path=str(source)))


def test_probe_rejects_zero_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "zero.wav"
    source.write_bytes(b"x")
    result = subprocess.CompletedProcess(
        [],
        0,
        stdout=json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "0"}}),
    )
    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", lambda *args, **kwargs: result)
    with pytest.raises(ValueError, match="measurable audio duration"):
        probe(Track(path=str(source)))


def test_trim_rejects_all_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    result = subprocess.CompletedProcess(
        [], 0, stderr=b"silence_start: 0\nsilence_end: 2\nsilence_start: 2"
    )
    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", lambda *args, **kwargs: result)
    with pytest.raises(ValueError, match="no audible audio"):
        detect_trim_bounds(Path("silent.wav"), duration=2)


def test_measure_loudness_handles_missing_and_nonfinite_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess([], 0, stderr="no loudnorm report")
    monkeypatch.setattr("ffkit.core.audio.analysis.subprocess.run", lambda *args, **kwargs: result)
    assert measure_loudness(Path("song.wav")) == (None, None)
    result.stderr = '{"input_i": "inf", "input_tp": "not a number"}'
    assert measure_loudness(Path("song.wav")) == (None, None)


def test_short_and_silent_audio_analysis(tmp_path: Path) -> None:
    short = tmp_path / "short.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.13",
            "-y",
            str(short),
        ],
        check=True,
    )
    assert analyze_waveform_tempo(probe(Track(path=str(short)))).waveform
    silent = tmp_path / "silent.wav"
    subprocess.run(  # noqa: S603 - Fixed FFmpeg test fixture command.
        [  # noqa: S607 - FFmpeg is resolved from PATH.
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono:d=0.3",
            "-y",
            str(silent),
        ],
        check=True,
    )
    analyzed = analyze_waveform_tempo(probe(Track(path=str(silent))))
    assert analyzed.waveform
    assert max(analyzed.waveform) == 0


def test_tempo_segment_transitions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "tone.wav"
    make_tone(source)
    estimates = [(0.0, 120.0, 0.5), (30.0, 60.0, 0.5), (60.0, 140.0, 0.5), (90.0, 140.0, 0.5)]
    monkeypatch.setattr("ffkit.core.audio.analysis.tempo_estimates", lambda energy: estimates)
    track = analyze_waveform_tempo(probe(Track(path=str(source))))
    assert [(segment.start, segment.bpm) for segment in track.tempo] == [
        (0.0, 90.0),
        (60.0, 140.0),
    ]
