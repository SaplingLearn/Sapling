"use client";
import { use } from "react";
import { SummaryEditor } from "@/components/screens/SummaryEditor/SummaryEditor";

export default function SummaryEditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <SummaryEditor summaryDocId={decodeURIComponent(id)} />;
}
