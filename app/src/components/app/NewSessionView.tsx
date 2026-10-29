import { useEffect, useRef, useState } from "react";
import { ChunkedRecorder } from "../../chunkedRecorder";
import { getSessionDetail, saveSessionNotes, startSession, stopSession, uploadChunk, type SessionDetail } from "../../sidecar";
import SessionContent from "./SessionContent";

type Phase = "idle" | "starting" | "recording" | "processing" | "done" | "error";

// WebKit's MediaRecorder reliably produces audio/mp4 (AAC) — verified
// against current WebKit docs (implementation-plan.md Step 12), which
// conveniently already matches data-model.md's audio.m4a naming. No
// transcoding needed before it reaches the backend.
const MIME_TYPE = "audio/mp4";

// How often to ask the backend for the slices transcribed so far.
const LIVE_POLL_MS = 4000;

export default function NewSessionView({
  courseId,
  onBack,
  onSessionCreated,
}: {
  courseId: number;
  onBack: () => void;
  onSessionCreated: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<SessionDetail | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");

  const recorderRef = useRef<ChunkedRecorder | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      // Leaving the page mid-recording stops the mic, but doesn't stop the
      // session server-side — there's no "abandon" endpoint (out of scope
      // for this pass). Slices already uploaded stay on the backend; the
      // slice being recorded is lost.
      recorderRef.current?.dispose();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Show the lecture as the slices get transcribed. A failed poll is not
  // worth interrupting a recording for: the next tick tries again.
  useEffect(() => {
    if (!sessionId || (phase !== "recording" && phase !== "processing")) return;
    const timer = setInterval(async () => {
      try {
        const detail = await getSessionDetail(courseId, sessionId);
        if (detail.transcript_so_far) setLiveTranscript(detail.transcript_so_far);
      } catch {
        /* retry on the next tick */
      }
    }, LIVE_POLL_MS);
    return () => clearInterval(timer);
  }, [courseId, sessionId, phase]);

  async function handleStart() {
    setPhase("starting");
    setError("");
    try {
      const { session_id, title } = await startSession(courseId);
      setSessionId(session_id);
      setSessionTitle(title);
      onSessionCreated();

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new ChunkedRecorder(stream, MIME_TYPE, (index, slice) => uploadChunk(session_id, index, slice), setElapsed);
      recorder.start();
      recorderRef.current = recorder;

      setElapsed(0);
      setPaused(false);
      setPhase("recording");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't start recording — check microphone permission.");
      setPhase("error");
    }
  }

  function handlePauseResume() {
    const recorder = recorderRef.current;
    if (!recorder) return;
    if (paused) {
      recorder.resume();
      setPaused(false);
    } else {
      recorder.pause();
      setPaused(true);
    }
  }

  async function handleStop() {
    const recorder = recorderRef.current;
    if (!recorder || !sessionId) return;
    setPaused(false);
    setPhase("processing");

    try {
      const lastSlice = await recorder.stop();
      await stopSession(sessionId, lastSlice);
      pollRef.current = setInterval(async () => {
        const detail = await getSessionDetail(courseId, sessionId);
        if (detail.status === "done" || detail.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          setResult(detail);
          setError(detail.error ?? "Something went wrong processing the recording.");
          setPhase(detail.status);
          onSessionCreated();
        }
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong processing the recording.");
      setPhase("error");
    }
  }

  function handleNotesBlur() {
    if (sessionId) saveSessionNotes(sessionId, notes).catch(() => {});
  }

  function formatElapsed(s: number): string {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  return (
    <section id="view-new-session">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="assign-head">
        <h2>{sessionTitle ?? "New session"}</h2>
      </div>

      {phase === "idle" && (
        <div className="panel">
          <button className="btn-primary" onClick={handleStart}>
            Start recording
          </button>
        </div>
      )}

      {phase === "starting" && <p className="qa-thinking">Requesting microphone access…</p>}

      {(phase === "recording" || phase === "processing") && (
        <div className="split">
          <div className="panel">
            <h3>Recording</h3>
            {phase === "recording" ? (
              <>
                <div className="rec">
                  <span className={"rec-dot" + (paused ? " paused" : "")} aria-hidden="true"></span>
                  <b className="rec-time">{formatElapsed(elapsed)}</b>
                  {paused && <span className="muted">Paused</span>}
                </div>
                <div className="recording-actions">
                  <button className="btn-secondary" onClick={handlePauseResume}>
                    {paused ? "Resume" : "Pause"}
                  </button>
                  <button className="btn-primary" onClick={handleStop}>
                    Stop recording
                  </button>
                </div>
              </>
            ) : (
              <p className="qa-thinking">Transcribing and generating notes…</p>
            )}
            <h3>Live transcript</h3>
            <p className="live-transcript">
              {liveTranscript || "The transcript appears here about half a minute after you start talking."}
            </p>
          </div>
          <div className="panel">
            <h3>Notes</h3>
            <textarea
              className="notes-area"
              placeholder="Jot down anything worth remembering. Enhanced notes are generated from the recording afterward, separately from this."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={handleNotesBlur}
            />
          </div>
        </div>
      )}

      {phase === "error" && <p className="qa-a-error">{error}</p>}

      {phase === "done" && result && <SessionContent transcript={result.transcript} summary={result.summary} />}
    </section>
  );
}
