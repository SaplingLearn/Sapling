import React from "react";
import { ShellFrame } from "@/components/ShellFrame";

export default function ShellLayout({ children }: { children: React.ReactNode }) {
  return <ShellFrame>{children}</ShellFrame>;
}
