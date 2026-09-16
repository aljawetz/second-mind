import { useState } from "react";
import type { ArtifactType, ViewName } from "../../types";
import { DATA, REAL_ASSIGNMENT_IDS, REAL_COURSE_IDS } from "../../data";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import HomeView from "./HomeView";
import SessionView from "./SessionView";
import ArtifactView from "./ArtifactView";
import AssignmentView from "./AssignmentView";

export default function AppShell() {
  const [course, setCourse] = useState<string>("49797");
  const [view, setView] = useState<ViewName>("home");
  const [session, setSession] = useState<string | null>(null);
  const [artifact, setArtifact] = useState<ArtifactType>("mocktest");
  const [assignment, setAssignment] = useState<string | null>(null);
  const [socratic, setSocratic] = useState(false);

  const courseData = DATA[course];

  function openSession(id: string) {
    setSession(id);
    setView("session");
  }
  function openArtifact(type: ArtifactType) {
    setArtifact(type);
    setView("artifact");
  }
  function openAssignment(id: string) {
    setAssignment(id);
    setView("assignment");
  }
  function goHome() {
    setView("home");
  }
  function changeCourse(code: string) {
    setCourse(code);
    setView("home");
  }

  return (
    <div id="stage-app">
      <div className="app">
        <Sidebar
          course={course}
          onCourseChange={changeCourse}
          activeSession={session}
          onOpenSession={openSession}
        />
        <main className="main">
          <Topbar course={courseData} courseCode={course} socratic={socratic} onToggleSocratic={() => setSocratic((s) => !s)} />
          <div className="view">
            <div className="view-inner">
              {view === "home" && (
                <HomeView
                  course={courseData}
                  courseCode={course}
                  courseId={REAL_COURSE_IDS[course] ?? null}
                  socratic={socratic}
                  onOpenSession={openSession}
                  onOpenArtifact={openArtifact}
                  onOpenAssignment={openAssignment}
                />
              )}
              {view === "session" && session && (
                <SessionView course={courseData} sessionId={session} onBack={goHome} />
              )}
              {view === "artifact" && (
                <ArtifactView
                  course={courseData}
                  courseCode={course}
                  artifact={artifact}
                  onArtifactChange={setArtifact}
                  onBack={goHome}
                />
              )}
              {view === "assignment" && assignment && (
                <AssignmentView
                  course={courseData}
                  assignmentId={assignment}
                  courseId={REAL_COURSE_IDS[course] ?? null}
                  realAssignmentId={REAL_ASSIGNMENT_IDS[assignment] ?? null}
                  onBack={goHome}
                />
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
