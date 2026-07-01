"use client";
import React from "react";
import { Toggle } from "@/components/ui";

interface Props {
  semesters: string[];
  selected: string;
  onSelect: (semester: string) => void;
}

export function SemesterChips({ semesters, selected, onSelect }: Props) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Toggle
        options={semesters.map((s) => ({ value: s, label: s }))}
        value={selected}
        onChange={onSelect}
        size="sm"
        wrap
      />
    </div>
  );
}
