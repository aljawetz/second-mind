// Records the lecture in standalone slices and uploads each one as soon as
// it is complete, so the backend can transcribe while the class is still
// going and stopping only waits for the last slice.
//
// MediaRecorder only writes a container header at the start of a recording,
// so slices are made by stopping the recorder and starting a new one on the
// same stream (a few ms of gap), not by asking one recorder for timeslices:
// those later pieces would not be playable on their own.

// 30s slices show the text in about half the time of 60s ones, and in
// benchmarks word accuracy from 15s to 60s slices stayed within run-to-run noise.
export const SLICE_SECONDS = 30;
const UPLOAD_ATTEMPTS = 3;

type Upload = (index: number, slice: Blob) => Promise<void>;

export class ChunkedRecorder {
  private slice!: { recorder: MediaRecorder; parts: Blob[] };
  private seconds = 0;
  private sliceSeconds = 0;
  private lastTick = 0;
  private nextIndex = 0;
  private paused = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private uploads: Promise<void> = Promise.resolve();
  private failed: { index: number; slice: Blob }[] = [];

  constructor(
    private stream: MediaStream,
    private mimeType: string,
    private upload: Upload,
    private onTick: (seconds: number) => void
  ) {}

  start() {
    this.beginSlice();
    this.lastTick = Date.now();
    this.timer = setInterval(() => {
      this.advanceClock();
      if (!this.paused && this.sliceSeconds >= SLICE_SECONDS) this.rotate();
    }, 1000);
  }

  // Time is measured on the clock, not by counting timer ticks: the webview
  // slows timers down when the window is in the background, and counting
  // ticks then made "60 second" slices up to twice as long.
  private advanceClock() {
    const now = Date.now();
    if (!this.paused) {
      const elapsed = (now - this.lastTick) / 1000;
      this.seconds += elapsed;
      this.sliceSeconds += elapsed;
      this.onTick(Math.floor(this.seconds));
    }
    this.lastTick = now;
  }

  pause() {
    this.advanceClock();
    this.slice.recorder.pause();
    this.paused = true;
  }

  resume() {
    this.lastTick = Date.now();
    this.slice.recorder.resume();
    this.paused = false;
  }

  // Ends the recording. Resolves with the final slice, which the caller
  // sends along with the stop request; every earlier slice has been
  // uploaded by then, or this rejects.
  async stop(): Promise<Blob> {
    if (this.timer) clearInterval(this.timer);
    const last = await this.finishSlice();
    this.stream.getTracks().forEach((t) => t.stop());
    await this.uploads;
    const failed = this.failed;
    this.failed = [];
    for (const { index, slice } of failed) await this.upload(index, slice);
    return last;
  }

  // For leaving the page mid-recording: stop the mic and the timer.
  dispose() {
    if (this.timer) clearInterval(this.timer);
    this.stream.getTracks().forEach((t) => t.stop());
  }

  private beginSlice() {
    const parts: Blob[] = [];
    const recorder = new MediaRecorder(this.stream, MediaRecorder.isTypeSupported(this.mimeType) ? { mimeType: this.mimeType } : undefined);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) parts.push(e.data);
    };
    recorder.start();
    this.slice = { recorder, parts };
    this.sliceSeconds = 0;
  }

  private finishSlice(): Promise<Blob> {
    const { recorder, parts } = this.slice;
    return new Promise((resolve) => {
      recorder.onstop = () => resolve(new Blob(parts, { type: this.mimeType }));
      recorder.stop();
    });
  }

  private rotate() {
    const finished = this.finishSlice();
    const index = this.nextIndex++;
    this.beginSlice();
    this.uploads = this.uploads.then(async () => this.send(index, await finished));
  }

  // Uploads are chained so slices go up in order; a slice that still fails
  // after a few tries is kept and retried when the recording stops.
  private async send(index: number, slice: Blob) {
    for (let attempt = 1; attempt <= UPLOAD_ATTEMPTS; attempt++) {
      try {
        await this.upload(index, slice);
        return;
      } catch {
        if (attempt < UPLOAD_ATTEMPTS) await new Promise((r) => setTimeout(r, attempt * 1000));
      }
    }
    this.failed.push({ index, slice });
  }
}
