import { useState } from "react";
import type { AvailableCourse, OnboardStage } from "./types";
import StartupGate from "./components/onboarding/StartupGate";
import OnboardingKeys from "./components/onboarding/OnboardingKeys";
import OnboardingCourses from "./components/onboarding/OnboardingCourses";
import OnboardingIndexing from "./components/onboarding/OnboardingIndexing";
import AppShell from "./components/app/AppShell";

export default function App() {
  const [stage, setStage] = useState<OnboardStage>("startup");
  const [courses, setCourses] = useState<AvailableCourse[]>([]);
  const selectedCourses = courses.filter((c) => c.checked);

  switch (stage) {
    case "startup":
      return <StartupGate onReady={() => setStage("keys")} />;
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
      return <AppShell courses={selectedCourses} />;
  }
}
