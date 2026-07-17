"""Audio preprocessing for browser-recorded speech chunks."""

from __future__ import annotations

import base64
import binascii
import io
import math

from pydub import AudioSegment


def _strip_data_url(audio_base64: str) -> str:
    value = audio_base64.strip()
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def preprocess_audio_for_stt(audio_base64: str, input_format: str = "webm") -> bytes:
    """Convert Base64 browser audio to WAV PCM 16-bit, 16kHz, mono.

    Supports raw Base64 and `data:audio/...;base64,...` strings. WebM/MP3/MP4
    decoding requires ffmpeg in the runtime image.
    """
    try:
        raw_bytes = base64.b64decode(_strip_data_url(audio_base64), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("audio_base64 is not valid Base64") from exc

    if not raw_bytes:
        raise ValueError("audio_base64 is empty")

    audio_stream = io.BytesIO(raw_bytes)
    fmt = (input_format or "webm").lower().split(";")[0].strip()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[1]
    try:
        segment = AudioSegment.from_file(audio_stream, format=fmt)
    except Exception:
        audio_stream.seek(0)
        try:
            segment = AudioSegment.from_file(audio_stream)
        except Exception as exc:
            raise ValueError(f"could not decode audio as {fmt}") from exc

    segment = segment.set_channels(1).set_frame_rate(16000).set_sample_width(2)

    if math.isfinite(segment.max_dBFS):
        segment = segment.apply_gain(-3.0 - segment.max_dBFS)

    out_buf = io.BytesIO()
    segment.export(out_buf, format="wav")
    return out_buf.getvalue()
