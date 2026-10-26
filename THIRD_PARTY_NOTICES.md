# Third-party components and data

The [MIT license](LICENSE) applies to project-owned code and documentation.
It does not replace the licenses below.

| Component | Use / distribution | License and source |
| --- | --- | --- |
| Manrope | Included `deliverables/ui/frontier-instrument/fonts/Manrope.ttf` | SIL OFL 1.1, Copyright 2018 The Manrope Project Authors; full [OFL.txt](deliverables/ui/frontier-instrument/fonts/OFL.txt), [upstream](https://github.com/googlefonts/manrope) |
| Pillow 13.0.0 | Installed into `.venv`; not vendored in the application archive | HPND and bundled dependency notices; [license](https://github.com/python-pillow/Pillow/blob/main/LICENSE), [package](https://pypi.org/project/pillow/13.0.0/) |
| pypdf 6.21.2 | Installed into `.venv` for bounded PDF extraction; not vendored | BSD-3-Clause; [package](https://pypi.org/project/pypdf/6.21.2/), [license](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |
| imageio-ffmpeg 0.6.0 | Installed into `.venv`; setup copies its wheel's FFmpeg to local `.lab-tools/media` | Wrapper BSD-2-Clause; binary has its own build license, not the wrapper's BSD; [upstream](https://github.com/imageio/imageio-ffmpeg), [package](https://pypi.org/project/imageio-ffmpeg/0.6.0/) |
| FFmpeg | Local H.264 encoder obtained during setup; not bundled in the application ZIP | License depends on enabled libraries/build; inspect `ffmpeg.exe -L` and `-buildconf`; [legal information](https://ffmpeg.org/legal.html) |
| CPython | User-installed runtime, not bundled | [Python license](https://docs.python.org/3/license.html) |
| BEIR / SciFact | Optional separately downloaded data; no corpus or author's receipt in the release | Claims/evidence CC BY 4.0, S2ORC abstracts ODC-By 1.0; [attribution](docs/research/lexical-pilot.md), [original license](https://github.com/allenai/scifact/blob/master/LICENSE.md) |

Installed packages retain upstream licenses and metadata in `.venv`.
Redistribution of added binaries or datasets requires retaining and reviewing
their upstream notices and terms. The local encoder checksum identifies bytes;
it does not make FFmpeg project-owned.

Codex, Claude Code and Telegram are optional external products/services.
Executables, accounts, subscriptions, trademarks and service terms are not
included or relicensed. No model weights are distributed.
