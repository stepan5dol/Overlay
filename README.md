# Overlay

Turns a book into a book that reads itself: the text highlights as the audio
plays. Drop in an EPUB or a PDF, get back an EPUB 3 with Media Overlays —
or an M4B audiobook.

Everything runs locally on Apple Silicon. No cloud, no API keys.

## What it does

- **EPUB in, EPUB out.** The narration is added *into* your book: layout,
  images and styles stay exactly as they were.
- **PDF in.** Parsed with [docling](https://github.com/docling-project/docling),
  which separates body text from running heads and keeps figures and tables.
- **Four voice engines**, installed on demand from the app:

  | engine | voices | speed | clones a voice |
  |---|---|---|---|
  | Qwen3-TTS | your own sample, 9 presets | 9× with batching | yes |
  | Kokoro | 28 English | 19× | no |
  | Kokoro RU | Sveta, Masha, Dima | 18× | no |
  | System (macOS) | installed system voices | instant | no |

  Speeds measured on an M4 Pro, relative to real time.

- **Word-level highlighting** when using system voices: `AVSpeechSynthesizer`
  reports the range of every spoken word, so no forced alignment is needed.
  Other engines highlight sentence by sentence.

## Requirements

- macOS 26 or later, Apple Silicon
- `ffmpeg` (`brew install ffmpeg`)
- ~3 GB of disk per engine, downloaded on first use

## Install

Download the DMG from [Releases](../../releases), or build it yourself:

```sh
git clone https://github.com/stepan5dol/Overlay
cd overlay
app/build.sh
```

## Command line

```sh
python3 src/book.py BOOK.epub                    # or BOOK.pdf
python3 src/book.py BOOK.epub --voice sveta --format both
python3 src/book.py --list-voices
```

Nothing is required beyond the file itself: the language is detected from the
book, a matching voice is picked, and missing engines are installed on demand.

## Voice samples

`refs/` holds reference recordings used for voice cloning, each with its
transcript — cloning needs an accurate one. All shipped samples are public
domain: [LJSpeech](https://keithito.com/LJ-Speech-Dataset/) (Linda Johnson) and
[LibriVox](https://librivox.org) (Bryan Ness, Meredith Hughes).

To add your own: put `name.wav` (10 seconds of clean speech) and `name.txt`
with its exact transcript into `refs/`.

**Please only clone a voice you have permission to use.**

## Third-party licences

The code here is MIT. The models and libraries it downloads have their own:
Qwen3-TTS and Kokoro under Apache 2.0, `kokoro-ru` weights under OpenRAIL,
`ffmpeg` under GPL (used as an external binary, not linked).
