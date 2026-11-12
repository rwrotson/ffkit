from ffkit.audio import Effects, audio_filters


def test_filters_use_fixed_notation_for_small_values() -> None:
    assert audio_filters(Effects(trim_start=1e-5, gain_db=1e-5)) == [
        "atrim=start=0.00001",
        "asetpts=PTS-STARTPTS",
        "volume=0.00001dB",
    ]


def test_filters_keep_order_and_stream_rule() -> None:
    assert audio_filters(Effects()) == []

    effects = Effects(
        trim_start=1,
        trim_end=4,
        trim_silence=True,
        silence_threshold_db=-45.5,
        gain_db=5,
        normalize_lufs=-14,
        limiter_ceiling_db=-1,
    )
    expected = [
        "atrim=start=1.0:end=4.0",
        "asetpts=PTS-STARTPTS",
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-45.5dB",
        "areverse",
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-45.5dB",
        "areverse",
        "volume=5.0dB",
        "loudnorm=I=-14.0:TP=-1:LRA=11",
        "alimiter=limit=0.89125094:level=false:latency=true",
    ]

    assert audio_filters(effects) == expected
    assert audio_filters(effects, streaming=True) == [*expected[:3], *expected[6:]]
    assert (
        audio_filters(effects.replace(limiter_ceiling_db=-3))[-1]
        == "alimiter=limit=0.70794578:level=false:latency=true"
    )

    assert audio_filters(Effects(trim_end=4))[:2] == [
        "atrim=start=0.0:end=4.0",
        "asetpts=PTS-STARTPTS",
    ]
