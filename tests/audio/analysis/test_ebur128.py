import importlib

ebur128 = importlib.import_module("ffkit.audio.analysis._ebur128")


def test_iter_lines_joins_chunks_and_bounds_unterminated_lines() -> None:
    long_line = b"x" * (ebur128.LINE_LIMIT * 3)

    assert list(ebur128.iter_lines([b"a\nb", b"c\n", b"d"])) == [b"a", b"bc", b"d"]
    assert list(ebur128.iter_lines([])) == [b""]
    assert list(ebur128.iter_lines([long_line[:10], long_line[10:]])) == [
        long_line[-ebur128.LINE_LIMIT :],
    ]


def test_report_passes_momentary_loudness_in_order() -> None:
    values: list[float | None] = []
    report = ebur128.Report(on_momentary=values.append)

    for line in (
        b"[Parsed_ametadata_1 @ 0x1] lavfi.r128.M=-120.691",
        b"[Parsed_ametadata_1 @ 0x1] lavfi.r128.M=-23.4",
        b"[Parsed_ametadata_1 @ 0x1] lavfi.r128.M=-inf",
        b"[Parsed_ametadata_1 @ 0x1] lavfi.r128.I=-23.0",
    ):
        report.read_line(line)

    assert values == [-120.691, -23.4, None]
    assert report.lufs() == -23.0


def test_report_ignores_momentary_loudness_without_a_consumer() -> None:
    report = ebur128.Report()

    report.read_line(b"lavfi.r128.M=-23.4")

    assert report.lufs() is None
