import { Suspense } from "react";
import { Calendar } from "@/components/screens/Calendar";

export default function CalendarPage() {
  return (
    <Suspense fallback={null}>
      <Calendar />
    </Suspense>
  );
}
