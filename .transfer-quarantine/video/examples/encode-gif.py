"""Read length-prefixed PNG frames on stdin and write one animated GIF."""

from __future__ import annotations

import struct
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image


def read_exact(size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sys.stdin.buffer.read(size - len(data))
        if not chunk:
            raise EOFError("frame stream ended early")
        data.extend(chunk)
    return bytes(data)


def main() -> None:
    output = Path(sys.argv[1])
    frame_count = int(sys.argv[2])
    frames: list[Image.Image] = []
    for _ in range(frame_count):
        (size,) = struct.unpack(">I", read_exact(4))
        with Image.open(BytesIO(read_exact(size))) as image:
            if image.size != (1600, 900):
                raise ValueError(f"unexpected frame size: {image.size}")
            frames.append(image.convert("RGB").quantize(colors=64, method=Image.Quantize.FASTOCTREE))
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        disposal=2,
        optimize=True,
    )
    print(f"{output.name}: {len(frames)} frames")


if __name__ == "__main__":
    main()
