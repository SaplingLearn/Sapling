import React from "react";
import { ShellFrame } from "@/components/ShellFrame";
import { OnboardingGate } from "@/components/OnboardingGate";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  // A student who hasn't finished onboarding is sent there from every app page.
  return (
    <OnboardingGate>
      <ShellFrame>{children}</ShellFrame>
    </OnboardingGate>
  );
}
