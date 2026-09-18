export type ArtifactType = "mocktest" | "mindmap" | "cards" | "slides";

export type ViewName = "home" | "artifact" | "assignment" | "newSession";

export type OnboardStage = "startup" | "keys" | "courses" | "indexing" | "app";

export interface AvailableCourse {
  id: number;
  code: string;
  name: string;
  checked: boolean;
}
