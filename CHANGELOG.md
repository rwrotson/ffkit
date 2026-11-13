# Changelog

All notable changes to this project will be documented in this file.

## v0.2.0 (2026-11-14)

First tagged release.

### Feat

- **audio**: add Effects.silence_min_duration, stream cancellation, and readable missing values in CLI text output
- **audio**: build waveform from one ebur128 and true-peak pass with per-channel min/max and --bins
- **audio**: detect silence with 20 ms RMS windows, pad trimmed edges, and add a peak-relative threshold
- **audio**: measure loudness with ebur128 as dual-mono and vectorize envelopes with numpy
- **audio**: estimate tempo with spectral flux and pulse-train scoring
- **cli**: add waveform and tempo commands, encoding options, and model-based JSON output
- add configurable Mp3Encoding and rename stream_mp3 to stream
- extend AudioInfo and accept info instead of duration
- raise typed FFKitError subclasses from a unified FFmpeg runner
- **core**: add embedded_cover to read the embedded cover image as bytes
- add FFmpegRuntime and public defaults, move logging to ffkit.logs, load FFKIT_* settings only in the CLI, and enforce layer contracts
- add FFmpegRuntime, move setup_logging to ffkit.logs behind the app extra, and enforce layer contracts
- **audio**: pass FFmpeg executables and timeouts through FFmpegRuntime
- **cli**: add normalization-gain and render cover/tag options
- **audio**: add analyze_loudness to fill the loudness cache
- **audio**: raise CancelledError on cancellation
- **cli**: show help without a command; ci: smoke-test the wheel and check the release tag version
- add optional Typer CLI for audio helpers
- add MP3 streaming cover extraction and normalization gain
- add safe MP3 rendering with peak limiting
- add FFmpeg audio probing and analysis
- add audio models and pure processing helpers

### Fix

- **cli**: print command failures once and log them to the file instead of the library
- **audio**: align detect_trim_bounds limits with Effects, skip hidden directories, and bound tempo memory
- **audio**: raise NoAudioError when the source has no audio stream
- **cli**: print text output without wrapping or emoji codes
- **audio**: map only attached pictures as covers
- **ffmpeg**: raise FFmpegNotFoundError for non-executable paths
- **ffmpeg**: measure stream idle time only while waiting for output
- **audio**: raise SourceNotFoundError for missing sources, keep sample rate after loudnorm, copy Opus stream tags, and bound normalize_lufs to the loudnorm range
- anchor gitignore patterns, track the logs package hidden by them, and add a hook against ignored sources
- **audio**: keep pauses when seeking a silence-trimmed stream, validate stream start, skip hidden files
- correct stream seeking, trim validation, ffmpeg number formatting, paths and tag overrides
- update vulnerable transitive dependencies
- use Self in Track validator annotation
- harden audio outputs and logging configuration
- verify embedded cover before replacing destination
- preserve audible tails in trim bound detection
- retain audible tails during silence trimming
- preserve tags, bound silence processing, and report file errors
- keep rounded normalization gain below peak ceiling
- refresh source tags when probing a track again
- read audio stream tags and document original-source effects
- enforce audio analysis timeouts and validate mutable trim bounds

### Refactor

- **audio**: move shared defaults to defaults.py and extract output path helpers
- **cli**: split app into root, shared helpers, and audio command modules
- **audio**: extract ebur128 report parsing into a private module
- **audio**: split tempo estimation out of the waveform module
- move file discovery, naming, and tag merging to ffkit.audio.library
- split waveform, peak envelope, and tempo estimation and hide filter helpers
- make options keyword-only, accept str paths, and add cancellation
- return Loudness and TrimBounds models and rename normalization helpers
- make Effects immutable and drop group gain and limiter parameters
- expose audio API as ffkit.audio and flatten core
- **core**: replace Track and Group with paths and Effects
- **core**: return analysis results instead of mutating Track
- **core**: make measure_loudness filters a keyword-only sequence
- **core**: default runtime to FFmpegRuntime() instead of None
- **core**: move FFmpeg runtime and process helpers from audio to core
- **audio**: split into analysis and processing subpackages
- **audio**: share subprocess helpers in _process
- **audio**: share trailing-silence and fingerprint helpers, reuse scan_silence for trim bounds, extract constants
- share silence scanning and encoder execution, extract audio constants, speed up peak waveform
- remove unnecessary future annotations imports
- group audio helpers under core audio package

### Perf

- **audio**: bound waveform astats frame size and split stderr lines in linear time
