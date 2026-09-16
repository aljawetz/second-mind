export interface Session {
  id: string;
  num: string;
  title: string;
  date: string;
  duration: string;
}

export type TranscriptRow = [time: string, text: string, current?: boolean];

export interface SessionDetail {
  transcript: TranscriptRow[];
  notes: string;
}

export interface MockQuestion {
  q: string;
  a: string;
  src: string;
}

export interface Flashcard {
  front: string;
  back: string;
}

export interface Slide {
  n: string;
  title: string;
  bullets: string[];
}

export interface Mindmap {
  center: string;
  nodes: string[];
}

export interface ExplainTip {
  text: string;
  src: string;
}

export interface AssignmentExplain {
  breakdown: string[];
  tips: ExplainTip[];
}

export interface Assignment {
  id: string;
  title: string;
  due: string;
  weight: string;
  status: string;
  prompt: string;
  explain: AssignmentExplain;
}

export interface Qa {
  q: string;
  a: string[];
  sources: string[];
}

export interface Course {
  code: string;
  sessions: Session[];
  qa: Qa;
  session: Record<string, SessionDetail>;
  mocktest: MockQuestion[];
  cards: Flashcard[];
  slides: Slide[];
  mindmap: Mindmap;
  assignments: Assignment[];
}

export type CourseData = Record<string, Course>;

export type ArtifactType = "mocktest" | "mindmap" | "cards" | "slides";

export type ViewName = "home" | "session" | "artifact" | "assignment";

export type OnboardStage = "startup" | "keys" | "courses" | "indexing" | "app";

export interface AvailableCourse {
  code: string;
  name: string;
  checked: boolean;
}
