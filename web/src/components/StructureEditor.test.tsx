import { fireEvent, screen } from "@testing-library/react";

import { renderPage } from "../test/utils";
import { PARTS, StructureEditor } from "./StructureEditor";

describe("StructureEditor", () => {
  it("puts a blue add button on the same row as each section heading", () => {
    renderPage(<StructureEditor nodes={[]} onSave={() => {}} />);
    for (const [part, label] of PARTS) {
      const row = screen.getByTestId(`structure-section-${part}`);
      expect(row.textContent).toContain(label);
      expect(row.style.borderTopWidth).toBe("1px");
      const button = row.querySelector("button");
      expect(button?.textContent).toContain("添加");
      expect(button?.className).toContain("ant-btn-link");
    }
    fireEvent.click(screen.getAllByRole("button", { name: /添加/ })[1]);
    const condition = screen.getByTestId("structure-section-condition");
    expect(condition.querySelectorAll("button")).toHaveLength(1);
    expect(document.getElementById("condition_0_text")).toBeTruthy();
  });
});
