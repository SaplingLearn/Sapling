// @vitest-environment jsdom
/**
 * ReportQuestion (spec §13 A113; GitHub #695): the "Report this question"
 * control the loop's check card and the review queue share.
 *   - closed, it is one small button; open, a fixed list of reasons — never a
 *     text box — and Cancel;
 *   - a reason calls onReport with its enum and closes once it resolves true;
 *     false (or a rejection) keeps the reasons open for another try;
 *   - every testid comes from the caller's prefix.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { REPORT_REASONS, ReportQuestion } from "./ReportQuestion";

afterEach(cleanup);

describe("ReportQuestion", () => {
  it("opens to the three reasons and nothing to type", () => {
    render(<ReportQuestion testIdPrefix="x-report" onReport={vi.fn()} />);
    expect(screen.queryByTestId("x-report-reasons")).toBeNull();
    fireEvent.click(screen.getByTestId("x-report"));
    const group = screen.getByTestId("x-report-reasons");
    expect(group.getAttribute("role")).toBe("group");
    expect(group.querySelector("textarea, input")).toBeNull();
    expect(REPORT_REASONS.map((r) => r.reason)).toEqual(["wrong_answer", "unclear", "not_from_my_course"]);
    for (const { reason } of REPORT_REASONS) expect(screen.getByTestId(`x-report-reason-${reason}`)).toBeTruthy();
  });

  it("sends the reason's enum and closes once the report is recorded", async () => {
    const onReport = vi.fn().mockResolvedValue(true);
    render(<ReportQuestion testIdPrefix="x-report" onReport={onReport} />);
    fireEvent.click(screen.getByTestId("x-report"));
    fireEvent.click(screen.getByTestId("x-report-reason-not_from_my_course"));
    expect(onReport).toHaveBeenCalledWith("not_from_my_course");
    await waitFor(() => expect(screen.queryByTestId("x-report-reasons")).toBeNull());
    expect(screen.getByTestId("x-report")).toBeTruthy();
  });

  it("stays open (and usable again) when the report is not recorded", async () => {
    const onReport = vi.fn().mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("down"));
    render(<ReportQuestion testIdPrefix="x-report" onReport={onReport} />);
    fireEvent.click(screen.getByTestId("x-report"));
    fireEvent.click(screen.getByTestId("x-report-reason-unclear"));
    await waitFor(() =>
      expect((screen.getByTestId("x-report-reason-unclear") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("x-report-reason-wrong_answer"));
    await waitFor(() =>
      expect((screen.getByTestId("x-report-reason-wrong_answer") as HTMLButtonElement).disabled).toBe(false),
    );
    expect(onReport).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("x-report-reasons")).toBeTruthy();
  });

  it("sends one report at a time and Cancel closes it", async () => {
    let finish!: (v: boolean) => void;
    const onReport = vi.fn(() => new Promise<boolean>((resolve) => { finish = resolve; }));
    render(<ReportQuestion testIdPrefix="x-report" onReport={onReport} />);
    fireEvent.click(screen.getByTestId("x-report"));
    fireEvent.click(screen.getByTestId("x-report-reason-unclear"));
    fireEvent.click(screen.getByTestId("x-report-reason-wrong_answer")); // disabled while busy
    expect(onReport).toHaveBeenCalledTimes(1);
    finish(false);
    await waitFor(() =>
      expect((screen.getByTestId("x-report-cancel") as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByTestId("x-report-cancel"));
    expect(screen.queryByTestId("x-report-reasons")).toBeNull();
  });

  it("is disabled with its card", () => {
    render(<ReportQuestion testIdPrefix="x-report" disabled onReport={vi.fn()} />);
    expect((screen.getByTestId("x-report") as HTMLButtonElement).disabled).toBe(true);
  });
});
