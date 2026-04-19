"use client";
import React from "react";
import { Icon } from "./Icon";
import { ReportIssueFlow } from "./ReportIssueFlow";

export function FloatingActions() {
  const [reportOpen, setReportOpen] = React.useState(false);
  return (
    <>
      <div style={{ position: "fixed", bottom: 20, right: 20, display: "flex", gap: 8, zIndex: 40 }}>
        <button
          className="btn btn--sm"
          onClick={() => setReportOpen(true)}
          title="Tell us what's wrong"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent)",
            borderColor: "var(--accent-border)",
            boxShadow: "var(--shadow-md)",
          }}
        >
          <Icon name="bell" size={13} /> Report
        </button>
      </div>
      <ReportIssueFlow open={reportOpen} onClose={() => setReportOpen(false)} />
    </>
  );
}
