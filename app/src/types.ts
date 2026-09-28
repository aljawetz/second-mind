export type ArtifactType = "mocktest" | "mindmap" | "cards";

export type ViewName =
  | "home"
  | "artifact"
  | "assignment"
  | "newSession"
  | "sessionDetail"
  | "manageCourses"
  | "manageMemories"
  | "indexingCourse";

export type OnboardStage = "startup" | "keys" | "courses" | "indexing" | "app";

export interface AvailableCourse {
  id: number;
  code: string;
  name: string;
  checked: boolean;
}
