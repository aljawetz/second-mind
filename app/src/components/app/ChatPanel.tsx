import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { askQuestion, getConversation, type Citation, type MemoryUsed } from "../../sidecar";
import Answer, { stripCitations } from "./Answer";

interface ChatTurn {
  question: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  memoriesUsed: MemoryUsed[];
  status: "loading" | "streaming" | "done" | "error";
  error?: string;
}

export default function ChatPanel({
  courseId,
  courseName,
  conversationId: initialConversationId,
  suggestions,
  initialQuestion,
  onInitialQuestionSent,
  onConversationSaved,
  onOpenCitation,
}: {
  courseId: number;
  courseName: string;
  // A saved chat to open, or null for a new one.
  conversationId: string | null;
  suggestions: string[];
  // Asked as soon as the panel opens: Explain on a quiz question or flashcard.
  initialQuestion?: string | null;
  onInitialQuestionSent?: () => void;
  onConversationSaved: (conversationId: string) => void;
  onOpenCitation: (c: Citation) => void;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [title, setTitle] = useState<string | null>(null);
  // The backend's id for this chat, from its first answer: sent with every
  // later question so the chat continues where it is saved.
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [opening, setOpening] = useState(initialConversationId !== null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [askValue, setAskValue] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);
  // An answer keeps streaming after the student navigates away; only a
  // mounted panel may tell AppShell which chat is open.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Once only, also under StrictMode's double-run of effects.
  const initialSent = useRef(false);
  useEffect(() => {
    if (!initialQuestion || initialSent.current) return;
    initialSent.current = true;
    void send(initialQuestion);
    onInitialQuestionSent?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lastTurn = turns[turns.length - 1];
  const busy = lastTurn?.status === "loading" || lastTurn?.status === "streaming";

  // Load the saved chat once, on open. The id prop also changes when this
  // panel's own new chat gets saved, and reloading then would replace the
  // answer on screen. Picking another chat remounts the panel instead.
  useEffect(() => {
    if (!initialConversationId) return;
    let cancelled = false;
    getConversation(courseId, initialConversationId)
      .then((c) => {
        if (cancelled) return;
        setTitle(c.title);
        setTurns(
          c.turns.map((t) => ({
            question: t.question,
            answer: t.answer,
            citations: t.citations,
            grounded: t.grounded,
            memoriesUsed: [],
            status: "done" as const,
          }))
        );
      })
      .catch((err) => {
        if (!cancelled) setOpenError(err instanceof Error ? err.message : "Couldn't open this chat");
      })
      .finally(() => {
        if (!cancelled) setOpening(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow the answer as it streams, unless the student scrolled up to read.
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  function handleScroll() {
    const el = threadRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function resizeInput() {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setAskValue("");
    requestAnimationFrame(resizeInput);
    stickToBottom.current = true;
    if (!title) setTitle(question);
    const turnIndex = turns.length;
    // Only finished turns: an errored or half-streamed answer would give the
    // model a wrong picture of what it already said.
    const history = turns.filter((t) => t.status === "done").map((t) => ({ question: t.question, answer: t.answer }));
    setTurns((prev) => [
      ...prev,
      { question, answer: "", citations: [], grounded: false, memoriesUsed: [], status: "loading" },
    ]);

    const update = (patch: Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t, i) => (i === turnIndex ? { ...t, ...patch } : t)));

    let streamFailed = false;
    // main.py sends the chat's id on the stream's first line only, and saves
    // the turn when the answer is done.
    let savedAs: string | null = null;
    try {
      await askQuestion(courseId, courseName, question, history, conversationId, (event) => {
        if (event.conversation_id) savedAs = event.conversation_id;
        if (event.delta) {
          setTurns((prev) =>
            prev.map((t, i) => (i === turnIndex ? { ...t, answer: t.answer + event.delta, status: "streaming" } : t))
          );
        }
        if (event.citations !== undefined) {
          update({ citations: event.citations, grounded: !!event.grounded, memoriesUsed: event.memories_used ?? [] });
        }
        if (event.error) {
          streamFailed = true;
          update({ status: "error", error: event.error });
        }
        if (event.done) {
          if (!streamFailed && savedAs) {
            setConversationId(savedAs);
            if (mounted.current) onConversationSaved(savedAs);
          }
          setTurns((prev) =>
            prev[turnIndex]?.status === "error"
              ? prev
              : prev.map((t, i) => (i === turnIndex ? { ...t, status: "done" } : t))
          );
        }
      });
    } catch (err) {
      update({ status: "error", error: err instanceof Error ? err.message : "Something went wrong" });
    }
  }

  async function copy(i: number) {
    try {
      await navigator.clipboard.writeText(stripCitations(turns[i].answer));
      setCopied(i);
      setTimeout(() => setCopied((c) => (c === i ? null : c)), 1500);
    } catch {
      // Clipboard refused: nothing useful to show beyond the unchanged label.
    }
  }

  const empty = !opening && !openError && turns.length === 0;

  return (
    <section className="chat-card" aria-label="Chat">
      <div className="chat-top">
        <h2>{title ?? "New chat"}</h2>
        {turns.length > 0 && (
          <span className="when">
            {turns.length} {turns.length === 1 ? "question" : "questions"}
          </span>
        )}
      </div>

      {empty ? (
        <div className="chat-empty">
          <h2>Ask about {courseName}</h2>
          <p>Answers come from your slides, recordings and Canvas pages, with footnotes to each source.</p>
          {suggestions.length > 0 && (
            <div className="suggest">
              {suggestions.map((s) => (
                <button key={s} type="button" onClick={() => void send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="qa-thread" ref={threadRef} onScroll={handleScroll}>
          <div className="qa-col">
            {opening && <p className="qa-thinking">Opening this chat…</p>}
            {openError && <p className="qa-a-error">{openError}</p>}
            {turns.map((turn, i) => (
              <div className="qa-turn" key={i}>
                <div className="qa-q">{turn.question}</div>
                {turn.status === "error" ? (
                  <div className="qa-a qa-a-error">{turn.error}</div>
                ) : (
                  <div className="qa-a">
                    {turn.status === "loading" ? (
                      <p className="qa-thinking">Searching your course…</p>
                    ) : (
                      <Answer
                        answer={turn.answer}
                        citations={turn.citations}
                        grounded={turn.grounded}
                        memoriesUsed={turn.memoriesUsed}
                        onOpenCitation={onOpenCitation}
                        actions={
                          turn.status === "done" && (
                            <div className="qa-actions">
                              <button type="button" onClick={() => void copy(i)}>
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                  <rect x="9" y="9" width="11" height="11" rx="2" />
                                  <path d="M5 15V5a2 2 0 0 1 2-2h10" />
                                </svg>
                                {copied === i ? "Copied" : "Copy"}
                              </button>
                              <button type="button" disabled={busy} onClick={() => void send(turn.question)}>
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                  <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5" />
                                </svg>
                                Ask again
                              </button>
                            </div>
                          )
                        }
                      />
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(askValue);
        }}
      >
        <div className="ask-box">
          <textarea
            ref={inputRef}
            rows={1}
            aria-label={`Ask about ${courseName}`}
            placeholder="Ask about this course…"
            value={askValue}
            onChange={(e) => {
              setAskValue(e.target.value);
              resizeInput();
            }}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter adds a line. Not while an input
              // method is composing, or picking a Chinese candidate would send.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(askValue);
              }
            }}
          />
          <button className="ask-send" type="submit" disabled={busy || !askValue.trim()}>
            Ask
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </form>
    </section>
  );
}
