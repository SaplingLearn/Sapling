import { Suspense } from "react";
import { Dashboard } from "@/components/screens/Dashboard";

export default function DashboardPage() {
  return (
    <Suspense fallback={null}>
      <Dashboard />
    </Suspense>
  );
}
