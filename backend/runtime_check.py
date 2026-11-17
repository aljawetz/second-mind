"""Offline checks executed by the actual frozen backend before packaging."""

import json
import tempfile
from pathlib import Path


def run() -> None:
    print("Checking native libraries and local models...", flush=True)
    import av
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    import embeddings
    import indexing
    import sessions
    from native_tools import image_to_string

    # Exercise DLL loading, model data, and real inference, not just imports.
    vector = embeddings.OnnxBgeEmbedding().get_text_embedding("Windows compatibility check")
    assert len(vector) == 384 and all(np.isfinite(vector)), "embedding inference failed"
    print("Embedding inference: OK", flush=True)
    with tempfile.TemporaryDirectory(prefix="Second Mind 日本語 ") as directory:
        root = Path(directory)
        import lancedb

        db = lancedb.connect(str(root / "index.lancedb"))
        table = db.create_table("smoke", [{"id": "lecture", "vector": vector, "text": "Course notes"}])
        assert table.search(vector).limit(1).to_list()[0]["id"] == "lecture"
        print("LanceDB in a Unicode path: OK", flush=True)

        # Recorders produce AAC/MP4 on macOS and Opus/WebM on Windows.
        # Keep the historical .m4a storage suffix: PyAV detects the container
        # from its header, so both must decode even with that suffix.
        model = sessions._get_model()
        for container, codec in (("mp4", "aac"), ("webm", "libopus")):
            path = root / f"{container}.m4a"
            with av.open(str(path), mode="w", format=container) as output:
                stream = output.add_stream(codec, rate=48000)
                stream.layout = "mono"
                frame = av.AudioFrame.from_ndarray(np.zeros((1, 48000), dtype=np.float32), format="flt", layout="mono")
                frame.sample_rate = 48000
                for packet in stream.encode(frame):
                    output.mux(packet)
                for packet in stream.encode(None):
                    output.mux(packet)
            # Force the Whisper encoder/decoder once even on silence;
            # exercise the bundled VAD model on the other container.
            segments, _ = model.transcribe(str(path), vad_filter=(container == "webm"))
            list(segments)
            print(f"{container} decoding and transcription: OK", flush=True)

        image = Image.new("RGB", (800, 120), "white")
        ImageDraw.Draw(image).text((20, 20), "SECOND MIND WINDOWS", font=ImageFont.load_default(size=48), fill="black")
        text = image_to_string(image)
        assert "SECOND" in text.upper() and "MIND" in text.upper(), f"OCR failed: {text!r}"
        print("OCR: OK", flush=True)

    # These modules are loaded lazily by the server; they must survive freezing.
    import chat
    import copilot_llm
    import github_signin
    import ingestion
    import study

    print(json.dumps({"status": "ok", "checks": ["embeddings", "lancedb", "mp4", "webm", "whisper", "ocr", "providers", "study"]}), flush=True)
