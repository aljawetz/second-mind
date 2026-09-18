import { useState } from "react";
import type { AvailableCourse, OnboardStage } from "./types";
import { getConfig, getCredentialsStatus, listCourses } from "./sidecar";
import StartupGate from "./components/onboarding/StartupGate";
import OnboardingKeys from "./components/onboarding/OnboardingKeys";
import OnboardingCourses from "./components/onboarding/OnboardingCourses";
import OnboardingIndexing from "./components/onboarding/OnboardingIndexing";
import AppShell from "./components/app/AppShell";

export default function App() {
  const [stage, setStage] = useState<OnboardStage>("startup");
  const [courses, setCourses] = useState<AvailableCourse[]>([]);
  const selectedCourses = courses.filter((c) => c.checked);

  // Returning-user check (config.json, data-model.md §3): skip onboarding
  // only when both credentials are in Keychain AND a remembered course
  // selection still matches a real, currently-available course. Any
  // failure here (backend hiccup, corrupted config, a remembered course
  // id that no longer exists) just falls through to normal onboarding —
  // never blocks startup on this being a returning user.
  async function handleBackendReady() {
    try {
      const [status, cfg] = await Promise.all([getCredentialsStatus(), getConfig()]);
      const remembered = cfg.selected_courses ?? [];
      if (status.canvas && status.openai && cfg.onboarding_complete && remembered.length > 0) {
        const allCourses = await listCourses();
        const restored = allCourses.map((c) => ({
          id: c.id,
          code: c.code ?? String(c.id),
          name: c.name,
          checked: remembered.includes(c.id),
        }));
        if (restored.some((c) => c.checked)) {
          setCourses(restored);
          setStage("app");
          return;
        }
      }
    } catch {
      // fall through to onboarding
    }
    setStage("keys");
  }

  // Unselecting/deleting a course (implementation-plan.md Step 13) only
  // ever happens from within AppShell, but the course list itself lives
  // here — mark it unchecked so selectedCourses (and everything derived
  // from it) shrinks on the next render. Removing the last one routes
  // back to course selection rather than leaving AppShell with nothing
  // to show.
  function handleCourseRemoved(courseId: number) {
    const remaining = courses.map((c) => (c.id === courseId ? { ...c, checked: false } : c));
    setCourses(remaining);
    if (!remaining.some((c) => c.checked)) {
      setStage("courses");
    }
  }

  // Adding a course post-onboarding (implementation-plan.md's UI feedback
  // round) — mirrors handleCourseRemoved's shape. `courses` may not already
  // contain this id at all (the returning-user restore path in
  // handleBackendReady only ever ran listCourses() once, before this course
  // was added), so this adds a fresh entry rather than assuming one exists
  // to flip a flag on.
  function handleCourseAdded(course: AvailableCourse) {
    setCourses((prev) => {
      const exists = prev.some((c) => c.id === course.id);
      return exists ? prev.map((c) => (c.id === course.id ? { ...c, checked: true } : c)) : [...prev, course];
    });
  }

  switch (stage) {
    case "startup":
      return <StartupGate onReady={handleBackendReady} />;
    case "keys":
      return <OnboardingKeys onNext={() => setStage("courses")} />;
    case "courses":
      return (
        <OnboardingCourses
          courses={courses}
          onChange={setCourses}
          onBack={() => setStage("keys")}
          onNext={() => setStage("indexing")}
        />
      );
    case "indexing":
      return <OnboardingIndexing courses={selectedCourses} onNext={() => setStage("app")} />;
    case "app":
      return <AppShell courses={selectedCourses} onCourseRemoved={handleCourseRemoved} onCourseAdded={handleCourseAdded} />;
  }
}
