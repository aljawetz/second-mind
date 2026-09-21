import { useEffect, useState } from "react";
import type { ArtifactType, AvailableCourse, ViewName } from "../../types";
import { listAssignments, listSessions, type CanvasAssignment, type SessionSummary } from "../../sidecar";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import HomeView from "./HomeView";
import ArtifactView from "./ArtifactView";
import AssignmentView from "./AssignmentView";
import NewSessionView from "./NewSessionView";
import SessionDetailView from "./SessionDetailView";
import ManageCoursesView from "./ManageCoursesView";
import OnboardingIndexing from "../onboarding/OnboardingIndexing";

export default function AppShell({
  courses,
  canvasBaseUrl,
  onCourseRemoved,
  onCourseAdded,
}: {
  courses: AvailableCourse[];
  canvasBaseUrl: string;
  onCourseRemoved: (courseId: number) => void;
  onCourseAdded: (course: AvailableCourse) => void;
}) {
  const [courseId, setCourseId] = useState<number>(courses[0].id);
  const [view, setView] = useState<ViewName>("home");
  const [artifact, setArtifact] = useState<ArtifactType>("mocktest");
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [assignments, setAssignments] = useState<CanvasAssignment[]>([]);
  const [assignmentsError, setAssignmentsError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [pendingIndexCourse, setPendingIndexCourse] = useState<AvailableCourse | null>(null);

  // The active course can disappear out from under this view (unselected
  // or deleted via Manage Courses) — fall back to whatever's left rather
  // than crash on course.find(...)! finding nothing.
  useEffect(() => {
    if (!courses.some((c) => c.id === courseId) && courses.length > 0) {
      setCourseId(courses[0].id);
      setView("home");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses]);

  const course = courses.find((c) => c.id === courseId);

  useEffect(() => {
    if (!course) return;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, !!course]);

  function refreshSessions() {
    if (!course) return;
    listSessions(courseId)
      .then(setSessions)
      .catch(() => {});
  }

  useEffect(() => {
    refreshSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, !!course]);

  // A session left "recording"/"processing" keeps polling in the
  // background while the sidebar is visible, so its status dot updates
  // even if the student navigates away from the session's own page.
  useEffect(() => {
    if (!sessions.some((s) => s.status === "recording" || s.status === "processing")) return;
    const id = setInterval(refreshSessions, 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, courseId]);

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
  function openNewSession() {
    setSessionId(null);
    setView("newSession");
  }
  function openSession(id: string) {
    setSessionId(id);
    setView("sessionDetail");
  }
  function handleSessionDeleted() {
    refreshSessions();
    goHome();
  }
  function openManageCourses() {
    setView("manageCourses");
  }
  function handleCourseRemoved(removedId: number) {
    onCourseRemoved(removedId);
  }
  // Selecting a course (ManageCoursesView.handleAdd's writeConfig) and
  // actually indexing its Canvas content are separate steps — this used
  // to skip straight to onCourseAdded, which made the course show up
  // everywhere (sidebar, /ask) while its manifest.db and LanceDB table
  // never got created, since syncCourse is only ever called from here.
  // Routing through the same indexing screen onboarding uses, scoped to
  // just this course, keeps that guarantee for every course, not only
  // the ones selected on first run.
  function handleCourseAdded(course: AvailableCourse) {
    setPendingIndexCourse(course);
    setView("indexingCourse");
  }
  function handleCourseIndexed() {
    if (pendingIndexCourse) onCourseAdded(pendingIndexCourse);
    setPendingIndexCourse(null);
    setView("manageCourses");
  }

  const selectedAssignment = assignments.find((a) => a.id === assignmentId) ?? null;

  // Removing the last course leaves nothing to render here — App.tsx owns
  // the course list and would need to route back to onboarding for that
  // case, not handled by this view.
  if (!course) {
    return null;
  }

  return (
    <div id="stage-app">
      <div className="app">
        <Sidebar
          courses={courses}
          activeCourseId={courseId}
          onCourseChange={changeCourse}
          onNewSession={openNewSession}
          sessions={sessions}
          activeSessionId={sessionId}
          onOpenSession={openSession}
          onManageCourses={openManageCourses}
        />
        <main className="main">
          <Topbar
            courseCode={course.code}
            courseName={course.name}
            overrideTitle={
              view === "manageCourses" ? "Manage courses" : view === "indexingCourse" ? "Manage courses" : undefined
            }
          />
          <div className={"view" + (view === "home" ? " view-fill" : "")}>
            <div className={"view-inner" + (view === "home" ? " view-inner-fill" : "")}>
              {view === "home" && (
                <HomeView
                  courseId={courseId}
                  courseName={course.name}
                  canvasBaseUrl={canvasBaseUrl}
                  assignments={assignments}
                  assignmentsError={assignmentsError}
                  onOpenArtifact={openArtifact}
                  onOpenAssignment={openAssignment}
                  onOpenSession={openSession}
                />
              )}
              {view === "artifact" && (
                <ArtifactView artifact={artifact} onArtifactChange={setArtifact} onBack={goHome} />
              )}
              {view === "assignment" && selectedAssignment && (
                <AssignmentView
                  courseId={courseId}
                  canvasBaseUrl={canvasBaseUrl}
                  assignment={selectedAssignment}
                  onBack={goHome}
                  onOpenSession={openSession}
                />
              )}
              {view === "newSession" && (
                <NewSessionView courseId={courseId} onBack={goHome} onSessionCreated={refreshSessions} />
              )}
              {view === "sessionDetail" && sessionId && (
                <SessionDetailView courseId={courseId} sessionId={sessionId} onBack={goHome} onDeleted={handleSessionDeleted} />
              )}
              {view === "manageCourses" && (
                <ManageCoursesView
                  courses={courses}
                  onBack={goHome}
                  onCourseRemoved={handleCourseRemoved}
                  onCourseAdded={handleCourseAdded}
                />
              )}
              {view === "indexingCourse" && pendingIndexCourse && (
                <OnboardingIndexing
                  courses={[pendingIndexCourse]}
                  onNext={handleCourseIndexed}
                  title={`Indexing ${pendingIndexCourse.code}`}
                  subtitle="This runs once for this course — after this, everything stays local."
                  showSteps={false}
                  continueLabel="Done →"
                />
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
