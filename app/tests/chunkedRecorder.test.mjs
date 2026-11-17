import assert from "node:assert/strict";
import { test } from "node:test";
import { ChunkedRecorder, recordingMimeType } from "../src/chunkedRecorder.ts";

test("selects a supported container and preserves the actual recorder MIME type", async () => {
  const original = globalThis.MediaRecorder;
  let supported = new Set(["audio/webm;codecs=opus"]);
  class Recorder {
    static isTypeSupported(type) { return supported.has(type); }
    constructor(_stream, options) { this.mimeType = options?.mimeType ?? "audio/webm"; }
    start() {}
    stop() {
      this.ondataavailable({ data: new Blob(["audio"], { type: this.mimeType }) });
      this.onstop();
    }
  }
  globalThis.MediaRecorder = Recorder;
  let trackStopped = false;
  const stream = { getTracks: () => [{ stop() { trackStopped = true; } }] };
  try {
    assert.equal(recordingMimeType(), "audio/webm;codecs=opus");
    supported = new Set(["audio/mp4", "audio/webm;codecs=opus"]);
    assert.equal(recordingMimeType(), "audio/mp4");
    supported = new Set();
    assert.equal(recordingMimeType(), undefined);
    const recorder = new ChunkedRecorder(stream, undefined, async () => {}, () => {});
    recorder.start();
    try {
      const blob = await recorder.stop();
      assert.equal(blob.type, "audio/webm");
      assert.equal(await blob.text(), "audio");
      assert.equal(trackStopped, true);
    } finally { recorder.dispose(); }
  } finally { globalThis.MediaRecorder = original; }
});
