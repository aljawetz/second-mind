import { useEffect, useRef, useState } from "react";
import { getSessionDetail, saveSessionNotes, startSession, stopSession, type SessionDetail } from "../../sidecar";
import SessionContent from "./SessionContent";

type Phase = "idle" | "starting" | "recording" | "processing" | "done" | "error";

// WebKit's MediaRecorder reliably produces audio/mp4 (AAC) — verified
// against current WebKit docs (implementation-plan.md Step 12), which
// conveniently already matches data-model.md's audio.m4a naming. No
// transcoding needed before it reaches the backend.
const MIME_TYPE = "audio/mp4";

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

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      // Leaving the page mid-recording stops the mic, but doesn't stop the
      // session server-side — there's no "abandon" endpoint (out of scope
      // for this pass); the recording is simply lost if not stopped first.
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timerRef.current) clearInterval(timerRef.current);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function handleStart() {
    setPhase("starting");
    setError("");
    try {
      const { session_id, title } = await startSession(courseId);
      setSessionId(session_id);
      setSessionTitle(title);
      onSessionCreated();

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, MediaRecorder.isTypeSupported(MIME_TYPE) ? { mimeType: MIME_TYPE } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.start();
      recorderRef.current = recorder;

      setElapsed(0);
      setPaused(false);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
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
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      setPaused(false);
    } else {
      recorder.pause();
      if (timerRef.current) clearInterval(timerRef.current);
      setPaused(true);
    }
  }

  function handleStop() {
    const recorder = recorderRef.current;
    if (!recorder || !sessionId) return;
    if (timerRef.current) clearInterval(timerRef.current);
    setPaused(false);
    setPhase("processing");

    recorder.onstop = async () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunksRef.current, { type: MIME_TYPE });
      try {
        await stopSession(sessionId, blob);
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
    };
    recorder.stop();
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
            ● Start recording
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
                <p className="mono">{paused ? "‖ Paused" : "●"} {formatElapsed(elapsed)}</p>
                <div className="recording-actions">
                  <button className="btn-secondary" onClick={handlePauseResume}>
                    {paused ? "▶ Resume" : "‖ Pause"}
                  </button>
                  <button className="btn-primary" onClick={handleStop}>
                    ■ Stop recording
                  </button>
                </div>
              </>
            ) : (
              <p className="qa-thinking">Transcribing and generating notes…</p>
            )}
          </div>
          <div className="panel">
            <h3>Notes</h3>
            <textarea
              className="notes-area"
              placeholder="Jot down anything worth remembering — enhanced notes are generated from the recording afterward, separately from this."
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
