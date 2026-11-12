# API Reference

The pages below are generated from public objects in `src/ffkit/`. Names exported from `ffkit` are the supported public API.

| Module | Purpose |
|--------|---------|
| `ffkit.core.errors` | Define the library error hierarchy |
| `ffkit.core.runtime` | Define FFmpeg executables and process time limits |
| `ffkit.core.audio.defaults` | Define default values for audio functions and CLI options |
| `ffkit.core.audio.files` | Discover supported audio inputs and build export names |
| `ffkit.core.audio.filters` | Build the FFmpeg audio filter chain |
| `ffkit.core.audio.tags` | Merge probed source tags with caller overrides |
| `ffkit.core.audio.models` | Define effects and analysis result models |
| `ffkit.core.audio.analysis.probe` | Read duration and tags |
| `ffkit.core.audio.analysis.silence` | Detect silence and trim bounds |
| `ffkit.core.audio.analysis.loudness` | Measure loudness and calculate normalization gain |
| `ffkit.core.audio.analysis.waveform` | Build waveforms and tempo estimates |
| `ffkit.core.audio.analysis.cover` | Read the embedded cover image |
| `ffkit.core.audio.processing.render` | Render non-destructive MP3 output |
| `ffkit.core.audio.processing.stream` | Stream MP3 audio from a playback position |
| `ffkit.core.audio.processing.cover` | Extract an embedded cover image |
| `ffkit.logs.settings` | Define logging settings |
| `ffkit.logs.setup` | Configure console and file logging for applications |
| `ffkit.cli.app` | Provide the optional Typer audio commands |
| `ffkit.cli.settings` | Define and load `FFKIT_*` settings of the command |
| `ffkit.main` | Start the optional CLI |
