import { useEffect, useState } from "react";
import type { AvailableCourse, ViewName } from "../../types";
import {
  deleteConversation,
  listAssignments,
  listConversations,
  listSessions,
  syncCourse,
  type CanvasAssignment,
  type ConversationSummary,
  type SessionSummary,
} from "../../sidecar";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import HomeView from "./HomeView";
import AssignmentView from "./AssignmentView";
import NewSessionView from "./NewSessionView";
import SessionDetailView from "./SessionDetailView";
import ManageCoursesView from "./ManageCoursesView";
import ManageMemoriesView from "./ManageMemoriesView";
import ModelProviderView from "./ModelProviderView";
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
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const [assignments, setAssignments] = useState<CanvasAssignment[]>([]);
  const [assignmentsError, setAssignmentsError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  // The chat open on course home: a saved one, or null for a new chat.
  const [conversationId, setConversationId] = useState<string | null>(null);
  // Bumped whenever the student picks a different chat, so the chat panel
  // starts fresh. Not bumped when a new chat gets saved under its id, which
  // would reload it mid-answer.
  const [chatKey, setChatKey] = useState(0);
  const [pendingIndexCourse, setPendingIndexCourse] = useState<AvailableCourse | null>(null);
  const [launchSyncing, setLaunchSyncing] = useState(false);
  const [launchSyncErrors, setLaunchSyncErrors] = useState<string[]>([]);
  const [launchSyncDetails, setLaunchSyncDetails] = useState<string[]>([]);

  // sync.py's own docstring states the design intent — "Runs once per app
  // launch, not a background daemon" — but nothing actually called
  // syncCourse for already-selected courses on launch; only onboarding and
  // the single-course add flow did. AppShell mounting *is* "entering the
  // app" for both a first-run and a returning user, so re-diffing every
  // selected course's manifest here (cheap when nothing changed — sync.diff
  // only re-embeds new/changed items) is what actually delivers that
  // intent. Runs once per mount, not per `courses` change, so it doesn't
  // refire while the single-course add flow's own indexing screen is open.
  useEffect(() => {
    let cancelled = false;
    async function syncOnLaunch() {
      setLaunchSyncing(true);
      const errors: string[] = [];
      const details: string[] = [];
      // Sequential — same reason as OnboardingIndexing: keeps each course's
      // manifest.db usage simple and avoids hammering Canvas at once.
      for (const c of courses) {
        if (cancelled) return;
        // The stream reports problems as events, not as a thrown error: a
        // terminal {done, error} when the course couldn't sync at all, and
        // {item, status: "failed", error} per item. Ignoring them hid a sync
        // where 28 of 29 PDFs failed behind a clean-looking launch.
        let courseError: string | null = null;
        const failed: string[] = [];
        try {
          await syncCourse(c.id, (event) => {
            if (event.done) {
              if (event.error) courseError = event.error;
            } else if (event.status === "failed") {
              failed.push(`${event.item ?? "?"}: ${event.error ?? "unknown error"}`);
            }
          });
        } catch (err) {
          courseError = err instanceof Error ? err.message : "sync failed";
        }
        if (courseError) {
          errors.push(`${c.code}: ${courseError}`);
          details.push(`${c.code}: ${courseError}`);
        } else if (failed.length > 0) {
          errors.push(`${c.code}: ${failed.length} ${failed.length === 1 ? "item" : "items"} failed`);
          details.push(`${c.code}:`, ...failed.map((f) => `  ${f}`));
        }
      }
      if (!cancelled) {
        setLaunchSyncErrors(errors);
        setLaunchSyncDetails(details);
        setLaunchSyncing(false);
      }
    }
    syncOnLaunch();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The active course can disappear out from under this view (unselected
  // or deleted via Manage Courses) — fall back to whatever's left rather
  // than crash on course.find(...)! finding nothing.
  useEffect(() => {
    if (!courses.some((c) => c.id === courseId) && courses.length > 0) {
      changeCourse(courses[0].id);
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

  function refreshConversations() {
    if (!course) return;
    listConversations(courseId)
      .then(setConversations)
      .catch(() => {});
  }

  useEffect(() => {
    setConversations([]);
    refreshConversations();
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

  function openChat(id: string | null) {
    setConversationId(id);
    setChatKey((k) => k + 1);
    setView("home");
  }
  function handleConversationSaved(id: string) {
    setConversationId(id);
    refreshConversations();
  }
  async function handleDeleteConversation(id: string) {
    await deleteConversation(courseId, id);
    if (id === conversationId) openChat(null);
    refreshConversations();
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
    setConversationId(null);
    setChatKey((k) => k + 1);
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
  function openModelProvider() {
    setView("modelProvider");
  }
  function openManageMemories() {
    setView("manageMemories");
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
          conversations={conversations}
          activeConversationId={view === "home" ? conversationId : null}
          onNewChat={() => openChat(null)}
          onOpenConversation={openChat}
          onDeleteConversation={handleDeleteConversation}
          sessions={sessions}
          activeSessionId={view === "sessionDetail" ? sessionId : null}
          onOpenSession={openSession}
          onNewSession={openNewSession}
          canvasBaseUrl={canvasBaseUrl}
          onManageCourses={openManageCourses}
          onModelProvider={openModelProvider}
        />
        <main className="main">
          <Topbar
            courseCode={course.code}
            courseName={course.name}
            onManageMemories={view === "home" ? openManageMemories : undefined}
            overrideTitle={
              view === "manageCourses"
                ? "Manage courses"
                : view === "manageMemories"
                  ? "Manage memories"
                  : view === "modelProvider"
                    ? "Model provider"
                    : view === "indexingCourse"
                      ? "Manage courses"
                      : undefined
            }
            syncStatus={
              launchSyncing
                ? { label: "Syncing courses…" }
                : launchSyncErrors.length > 0
                  ? { label: `Sync issue: ${launchSyncErrors.join("; ")}`, detail: launchSyncDetails.join("\n"), error: true }
                  : { label: "Synced with Canvas", ok: true }
            }
          />
          <div className={"view" + (view === "home" ? " view-home" : "")}>
            <div className="view-inner">
              {view === "home" && (
                <HomeView
                  key={`${courseId}-${chatKey}`}
                  courseId={courseId}
                  courseName={course.name}
                  canvasBaseUrl={canvasBaseUrl}
                  assignments={assignments}
                  assignmentsError={assignmentsError}
                  sessions={sessions}
                  conversationId={conversationId}
                  onConversationSaved={handleConversationSaved}
                  onOpenAssignment={openAssignment}
                  onOpenSession={openSession}
                />
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
              {view === "modelProvider" && <ModelProviderView onBack={goHome} />}
              {view === "manageMemories" && (
                <ManageMemoriesView
                  courseId={courseId}
                  courseCode={course.code}
                  courseName={course.name}
                  onBack={goHome}
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
