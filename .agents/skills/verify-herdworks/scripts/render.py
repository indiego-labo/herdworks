#!/usr/bin/env python3
"""Render saved terminal text to PNG, or timed screen JSON to an MP4."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import textwrap
import unicodedata
import zlib

# A tiny bitmap alphabet keeps rendering independent of installed fonts and GUI apps.
GLYPHS = """
20:0000000000 21:00005f0000 22:0007000700 23:147f147f14 24:242a7f2a12
25:2313086462 26:3649552250 27:0005030000 28:001c224100 29:0041221c00
2a:14083e0814 2b:08083e0808 2c:0050300000 2d:0808080808 2e:0060600000
2f:2010080402 30:3e5149453e 31:00427f4000 32:4261514946 33:2141454b31
34:1814127f10 35:2745454539 36:3c4a494930 37:0171090503 38:3649494936
39:064949291e 3a:0036360000 3b:0056360000 3c:0814224100 3d:1414141414
3e:0041221408 3f:0201510906 40:324979413e 41:7e1111117e 42:7f49494936
43:3e41414122 44:7f4141221c 45:7f49494941 46:7f09090901 47:3e4149497a
48:7f0808087f 49:00417f4100 4a:2040413f01 4b:7f08142241 4c:7f40404040
4d:7f020c027f 4e:7f0408107f 4f:3e4141413e 50:7f09090906 51:3e4151215e
52:7f09192946 53:4649494931 54:01017f0101 55:3f4040403f 56:1f2040201f
57:3f4038403f 58:6314081463 59:0708700807 5a:6151494543 5b:007f414100
5c:0204081020 5d:0041417f00 5e:0402010204 5f:4040404040 60:0001020400
61:2054545478 62:7f48444438 63:3844444420 64:384444487f 65:3854545418
66:087e090102 67:0c5252523e 68:7f08040478 69:00447d4000 6a:2040443d00
6b:7f10284400 6c:00417f4000 6d:7c04180478 6e:7c08040478 6f:3844444438
70:7c14141408 71:081414187c 72:7c08040408 73:4854545420 74:043f444020
75:3c4040207c 76:1c2040201c 77:3c4030403c 78:4428102844 79:0c5050503c
7a:4464544c44 7b:0008364100 7c:00007f0000 7d:0041360800 7e:0804081008
"""
FONT = {chr(int(pair.split(":")[0], 16)): bytes.fromhex(pair.split(":")[1]) for pair in GLYPHS.split()}


def lines_of(text, columns):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = text.translate(str.maketrans({"│": "|", "─": "-", "╭": "+", "╮": "+",
                                       "╰": "+", "╯": "+", "•": "*", "…": "...",
                                       "’": "'", "“": '"', "”": '"', "→": "->"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "replace").decode()
    return [part for line in text.expandtabs(4).splitlines()
            for part in (textwrap.wrap(line, columns, replace_whitespace=False, drop_whitespace=False) or [""])]


def png(text, output, columns=200, rows=None):
    lines = lines_of(text, columns)
    rows = rows or max(1, len(lines))
    scale, margin = 2, 20
    width, height = columns * 12 + margin * 2, rows * 18 + margin * 2
    data = bytearray(bytes((15, 23, 42)) * width * height)
    for row, line in enumerate(lines[:rows]):
        for col, char in enumerate(line[:columns]):
            for x, bits in enumerate(FONT.get(char, FONT["?"])):
                for y in range(7):
                    if bits & (1 << y):
                        px, py = margin + col * 12 + x * scale, margin + row * 18 + y * scale
                        for dy in range(scale):
                            offset = ((py + dy) * width + px) * 3
                            data[offset:offset + 6] = bytes((226, 232, 240)) * scale
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    pixels = b"".join(b"\0" + data[y * width * 3:(y + 1) * width * 3] for y in range(height))
    output.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)) +
                       chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def video(manifest, output, duration):
    entries = json.loads(manifest.read_text())
    if len(entries) < 2 or not 30 <= duration <= 60:
        raise ValueError("need at least two timed screens and a duration from 30 to 60 seconds")
    times = [float(entry["at"]) for entry in entries]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("screen times must strictly increase")
    texts = [(manifest.parent / entry["path"]).read_text() for entry in entries]
    rows = max(len(lines_of(text, 200)) for text in texts)
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        concat = []
        total = times[-1] - times[0]
        moving_duration = duration - 2
        for index, text in enumerate(texts):
            target = folder / f"{index:04}.png"
            png(text, target, rows=rows)
            hold = (times[index + 1] - times[index]) / total * moving_duration if index < len(times) - 1 else 2
            concat.extend([f"file '{target.name}'", f"duration {hold:.6f}"])
        concat.append(f"file '{target.name}'")
        listing = folder / "frames.txt"
        listing.write_text("\n".join(concat) + "\n")
        # Fill the concat holds before applying the output duration, including the final screen.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-vf", "fps=12,scale=1600:-2", "-t", str(duration),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="terminal text or timed screens JSON")
    parser.add_argument("output", type=Path, help=".png or .mp4")
    parser.add_argument("--duration", type=float, default=45)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix == ".png":
        png(args.input.read_text(), args.output)
    elif args.output.suffix == ".mp4":
        video(args.input, args.output, args.duration)
    else:
        parser.error("output must be .png or .mp4")
    print(args.output)


if __name__ == "__main__":
    main()
