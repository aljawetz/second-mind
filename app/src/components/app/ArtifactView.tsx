import type { ArtifactType } from "../../types";
import { ARTIFACT_TYPES } from "../../data";

export default function ArtifactView({
  artifact,
  onArtifactChange,
  onBack,
}: {
  artifact: ArtifactType;
  onArtifactChange: (type: ArtifactType) => void;
  onBack: () => void;
}) {
  const t = ARTIFACT_TYPES.find((x) => x.key === artifact)!;

  return (
    <section id="view-artifact">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="artifact-head">
        <h2>{t.lbl}</h2>
      </div>
      <div className="tabs">
        {ARTIFACT_TYPES.map((x) => (
          <button
            key={x.key}
            className={"tab" + (x.key === artifact ? " active" : "")}
            onClick={() => onArtifactChange(x.key)}
          >
            {x.lbl}
          </button>
        ))}
      </div>
      <div className="qa-empty">Study artifacts aren't built yet.</div>
    </section>
  );
}
