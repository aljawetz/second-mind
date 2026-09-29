export type ViewName =
  | "home"
  | "assignment"
  | "newSession"
  | "sessionDetail"
  | "manageCourses"
  | "manageMemories"
  | "modelProvider"
  | "indexingCourse";

export type OnboardStage = "startup" | "keys" | "courses" | "indexing" | "app";

export interface AvailableCourse {
  id: number;
  code: string;
  name: string;
  checked: boolean;
}
