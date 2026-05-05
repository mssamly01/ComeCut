# ComeCut-Py

A **pure-Python** port of the [ComeCut](../README%20copy.md) video editor —
ships as a CLI (Typer) and an optional desktop GUI (PySide6), both backed by
a common FFmpeg-driven engine.

> The original ComeCut is a Vue 3 SPA that runs the whole editor in the
> browser using WebCodecs, Canvas and AudioContext. This subproject replaces
> the browser runtime with native Python + FFmpeg so the editor can run
> headless (CI/automation) or on the desktop (PySide6).
>
> The original bundled HTML app is **not modified** — it still lives at the
> repo root and can still be served with the existing `Run-app-*.bat` scripts.

## Layout

```
python/
├── pyproject.toml
├── README.md                 ← this file
├── comecut_py/
│   ├── core/                 project model, timecode utils, ffmpeg command builder, ffprobe wrapper
│   ├── subtitles/            SRT / VTT / LRC parsers + writers + cross-format converter
│   ├── engine/               cut / concat / trim / overlay_text / burn-subs / render_project / audio ops
│   ├── ai/                   plugin architecture for AI providers (whisper_local etc., optional)
│   ├── i18n/                 small i18n helper + en / vi / zh locales
│   └── gui/                  PySide6 desktop UI (optional)
├── examples/
│   └── example_project.json
└── tests/
```

## Install

```bash
cd python
pip install -e .              # core + CLI
pip install -e ".[gui]"       # + PySide6 desktop GUI
pip install -e ".[ai]"        # + faster-whisper (offline transcription)
pip install -e ".[dev]"       # + pytest, ruff
pip install -e ".[all,dev]"   # everything
```

You also need `ffmpeg` and `ffprobe` on your `PATH`. On Ubuntu/Debian:

```bash
sudo apt install -y ffmpeg
```

## CLI quickstart

```bash
comecut-py --help                                        # list commands
comecut-py probe in.mp4                                  # ffprobe summary
comecut-py cut in.mp4 out.mp4 --start 00:00:05 --end 00:00:20
comecut-py concat a.mp4 b.mp4 c.mp4 -o all.mp4
comecut-py trim in.mp4 out.mp4 --head 2 --tail 3
comecut-py overlay-text in.mp4 out.mp4 -t "Hello!" --start 0 --end 3
comecut-py burn-subs in.mp4 subs.srt out.mp4
comecut-py extract-audio in.mp4 out.mp3
comecut-py volume in.mp4 out.mp4 0.5
comecut-py convert-subs subs.srt subs.vtt                # SRT/VTT/LRC interop
comecut-py transcribe in.mp4 out.srt --model small       # needs [ai] extras
comecut-py render project.json out.mp4                   # render a full project
comecut-py gui                                           # launch desktop editor
```

Every command accepts `--dry-run` to print the underlying ffmpeg invocation
without running it — handy for CI, debugging, and auditing.

## Project JSON format

See [`examples/example_project.json`](examples/example_project.json). The
schema is enforced by `pydantic` — see `comecut_py.core.project` for fields.

## GUI

The MVP GUI exposes four panels (media library / preview / timeline /
inspector) and a menu with Open / Save / Export. Clips can be dragged on the
timeline; the inspector edits in/out/start/volume in place. Preview uses the
system `QMediaPlayer` (single-clip scrubbing only — full multi-track preview
is on the roadmap).

## What is and is not ported

| Feature | Status |
| --- | --- |
| Timeline model (tracks, clips, overlays) | ✅ |
| Cut / concat / trim / overlay / burn-subs | ✅ |
| SRT / VTT / LRC parse + write + convert | ✅ |
| Full project render via ffmpeg `filter_complex` | ✅ (first pass) |
| `faster-whisper` local transcription | ✅ (optional extra) |
| Translation / TTS provider adapters | scaffold only |
| Desktop GUI (PySide6) | ✅ (MVP) |
| 100+ AI API providers from the web app | adapter interface only — implement per provider |
| Generative video (Sora2/Veo/Wan/Seedance/…) | out of scope |
| Hardware-accelerated live preview (WebCodecs) | out of scope — browser-only API |

## Plugins

Third-party packages can register custom AI providers (image-gen, video-gen,
TTS, voice clone) via Python entry points. The CLI commands `comecut-py
image-gen`, `video-gen`, `tts`, and `voice-clone` resolve `--provider <name>`
through the registry, so a plugin appears alongside the built-ins as soon
as its package is installed.

```toml
# my_plugin/pyproject.toml
[project.entry-points."comecut_py.video_providers"]
my-video = "my_plugin.providers:MyVideoGen"

[project.entry-points."comecut_py.image_providers"]
my-image = "my_plugin.providers:MyImageGen"

[project.entry-points."comecut_py.tts_providers"]
my-tts = "my_plugin.providers:MyTTS"

[project.entry-points."comecut_py.voice_clone_providers"]
my-cloner = "my_plugin.providers:MyCloner"
```

Each entry point must resolve to a callable (a class or factory function)
that accepts `**kwargs` from the CLI (typically `model=...`) and returns an
instance implementing the matching abstract base from
`comecut_py.ai.base` — `VideoProvider`, `ImageProvider`, `TTSProvider`, or
`VoiceCloneProvider`.

`comecut-py providers list` shows every registered provider and whether it
came from a builtin or from a plugin.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Unit tests cover the timecode parser, project model, subtitle parsers/writers
and the command-line builders — they **do not** shell out to ffmpeg, so CI
does not need the binary.

## License

AGPL-3.0, matching the upstream project.
