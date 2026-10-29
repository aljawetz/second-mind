import ReactMarkdown from "react-markdown";

export default function SessionContent({ transcript, summary }: { transcript?: string; summary?: string }) {
  return (
    <>
      <div className="panel">
        <h3>Enhanced notes</h3>
        {summary ? (
          <div className="markdown-body">
            <ReactMarkdown>{summary}</ReactMarkdown>
          </div>
        ) : (
          <div className="qa-empty">Nothing was transcribed. The recording may have been silent or too short.</div>
        )}
        {summary && <div className="indexed-tag">Indexed, searchable in answers and study material</div>}
      </div>
      {transcript && (
        <details className="panel">
          <summary>Full transcript</summary>
          <div className="assign-prompt">{transcript}</div>
        </details>
      )}
    </>
  );
}
