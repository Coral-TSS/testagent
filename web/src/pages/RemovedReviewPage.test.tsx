import { screen } from "@testing-library/react";

import { renderPage } from "../test/utils";
import { RemovedReviewPage } from "./RemovedReviewPage";

describe("RemovedReviewPage", () => {
  it("is a dead end for a bookmarked review URL", () => {
    renderPage(<RemovedReviewPage />, { path: "/versions/:versionId/review", route: "/versions/v1/review" });
    expect(screen.getByText("模型评审已移除")).toBeTruthy();
    expect(screen.getByRole("link", { name: "返回模型图谱" }).getAttribute("href")).toBe("/versions/v1/model");
    expect(screen.queryByText("已评审")).toBeNull();
  });
});
