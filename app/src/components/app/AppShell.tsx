import { useEffect, useState } from "react";
import type { ArtifactType, AvailableCourse, ViewName } from "../../types";
import { listAssignments, type CanvasAssignment } from "../../sidecar";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import HomeView from "./HomeView";
import ArtifactView from "./ArtifactView";
import AssignmentView from "./AssignmentView";

export default function AppShell({ courses }: { courses: AvailableCourse[] }) {
  const [courseId, setCourseId] = useState<number>(courses[0].id);
  const [view, setView] = useState<ViewName>("home");
  const [artifact, setArtifact] = useState<ArtifactType>("mocktest");
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [socratic, setSocratic] = useState(false);

  const [assignments, setAssignments] = useState<CanvasAssignment[]>([]);
  const [assignmentsError, setAssignmentsError] = useState<string | null>(null);

  const course = courses.find((c) => c.id === courseId)!;

  useEffect(() => {
    let cancelled = false;
    setAssignments([]);
    setAssignmentsError(null);
    listAssignments(courseId)
      .then((list) => {
        if (!cancelled) setAssignments(list);
      })
      .catch((err) => {
        if (!cancelled) setAssignmentsError(err instanceof Error ? err.message : "Couldn't load assignments");
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  function openArtifact(type: ArtifactType) {
    setArtifact(type);
    setView("artifact");
  }
  function openAssignment(id: number) {
    setAssignmentId(id);
    setView("assignment");
  }
  function goHome() {
    setView("home");
  }
  function changeCourse(id: number) {
    setCourseId(id);
    setView("home");
  }

  const selectedAssignment = assignments.find((a) => a.id === assignmentId) ?? null;

  return (
    <div id="stage-app">
      <div className="app">
        <Sidebar courses={courses} activeCourseId={courseId} onCourseChange={changeCourse} />
        <main className="main">
          <Topbar
            courseCode={course.code}
            courseName={course.name}
            socratic={socratic}
            onToggleSocratic={() => setSocratic((s) => !s)}
          />
          <div className="view">
            <div className="view-inner">
              {view === "home" && (
                <HomeView
                  courseId={courseId}
                  courseName={course.name}
                  assignments={assignments}
                  assignmentsError={assignmentsError}
                  socratic={socratic}
                  onOpenArtifact={openArtifact}
                  onOpenAssignment={openAssignment}
                />
              )}
              {view === "artifact" && (
                <ArtifactView artifact={artifact} onArtifactChange={setArtifact} onBack={goHome} />
              )}
              {view === "assignment" && selectedAssignment && (
                <AssignmentView courseId={courseId} assignment={selectedAssignment} onBack={goHome} />
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
