// `checked` = the exact (normalised) draft this verdict is about (#769), so
// save-on-blur can refuse a verdict that belongs to an earlier draft.
export type UsernameState = {
  status: "idle" | "checking" | "available" | "taken" | "invalid";
  message?: string;
  checked?: string;
};

/** Border colour of the username input: red for a rejected handle. */
export function usernameBorderColor(status: UsernameState["status"]): string {
  return status === "taken" || status === "invalid" ? "var(--err)" : "var(--border)";
}

/** Colour of the status line under the username input. */
export function usernameMessageColor(status: UsernameState["status"]): string {
  if (status === "available") return "var(--accent)";
  return status === "checking" ? "var(--text-muted)" : "var(--err)";
}

/** Text of the status line under the username input. */
export function usernameMessageText(state: UsernameState): string | undefined {
  return state.status === "checking" ? "Checking…" : state.message;
}
