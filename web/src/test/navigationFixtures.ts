import type { SutProgress } from "../api/types";

export const progress: SutProgress = {
  sut: { id: "s1", code: "PROC", name: "Procurement system" },
  version: { id: "v1", name: "v1", status: "frozen" },
  versions: [{ id: "v1", name: "v1", status: "frozen" }],
  steps: [
    { key: "sut", title: "被测系统", status: "done", summary: "1 个环境", path: "/suts/s1", action: null },
    { key: "model", title: "模型", status: "done", summary: "3 个实体", path: "/versions/v1/model", action: null },
    { key: "requirements", title: "需求", status: "done", summary: "2 个需求 · 已冻结", path: "/versions/v1", action: null },
    { key: "strategy", title: "策略", status: "doing", summary: "策略草稿", path: "/versions/v1/strategy", action: { label: "创建/确认测试策略", path: "/versions/v1/strategy" } },
    { key: "tasks", title: "任务", status: "todo", summary: "0 个任务", path: "/versions/v1/tasks", action: { label: "新建任务", path: "/versions/v1/tasks" } },
    { key: "cases", title: "用例", status: "todo", summary: "0 个用例", path: "/suts/s1/cases?version_id=v1", action: { label: "生成用例", path: "/suts/s1/cases?version_id=v1" } },
    { key: "runs", title: "执行", status: "todo", summary: "未执行", path: "/executions?sut_id=s1&version_id=v1", action: { label: "执行任务", path: "/versions/v1/tasks" } },
    { key: "results", title: "结果", status: "todo", summary: "无", path: "/defects?sut_id=s1&version_id=v1", action: null },
  ],
  next: { key: "strategy", title: "策略", label: "创建/确认测试策略", path: "/versions/v1/strategy" },
  repo_path: "D:/TestAgent/runtime/repos/PROC",
} as unknown as SutProgress;
