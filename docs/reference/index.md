# API Reference

The pages below are generated from public objects in `src/ffkit/`. Names exported from `ffkit` and `ffkit.audio` are the supported public API.

| Module | Purpose |
|--------|---------|
| `ffkit.errors` | Define the library error hierarchy |
| `ffkit.runtime` | Define FFmpeg executables and process time limits |
| `ffkit.audio.defaults` | Define default values for audio functions and CLI options |
| `ffkit.audio.effects` | Define the audio effects model |
| `ffkit.audio.encoding` | Define output encoder settings |
| `ffkit.audio.library.files` | Discover supported audio inputs and build export names |
| `ffkit.audio.library.tags` | Merge probed source tags with caller overrides |
| `ffkit.audio.analysis.probe` | Read duration and tags |
| `ffkit.audio.analysis.silence` | Detect silence and trim bounds |
| `ffkit.audio.analysis.loudness` | Measure loudness and calculate normalization gain |
| `ffkit.audio.analysis.waveform` | Build loudness and peak envelopes |
| `ffkit.audio.analysis.tempo` | Estimate tempo segments |
| `ffkit.audio.analysis.cover` | Read the embedded cover image |
| `ffkit.audio.processing.render` | Render non-destructive encoded output |
| `ffkit.audio.processing.stream` | Stream encoded audio from a playback position |
| `ffkit.audio.processing.extract` | Extract an embedded cover image to a file |
| `ffkit.logs.settings` | Define logging settings |
| `ffkit.logs.setup` | Configure console and file logging for applications |
| `ffkit.cli.app` | Provide the optional Typer audio commands |
| `ffkit.cli.settings` | Define and load `FFKIT_*` settings of the command |
| `ffkit.main` | Start the optional CLI |
