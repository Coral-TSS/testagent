import { useQuery } from "@tanstack/react-query";
import { Button, Input, List, Modal, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Correction } from "../api/types";
import { fmtTime } from "../utils/time";
import { ListSection } from "./ListView";

export const CORRECTION_STATUS: Record<string, [string, string]> = {
  pending: ["待处理", "default"],
  processing: ["处理中", "processing"],
  processed: ["已处理", "green"],
  failed: ["处理失败", "red"],
};

export function CorrectionStatusTag({ status }: { status: string }) {
  const [label, color] = CORRECTION_STATUS[status] || [status, "default"];
  return <Tag color={color}>{label}</Tag>;
}

interface Props {
  targetType: "case" | "strategy" | "requirement" | "execution" | "report" | "agent_run" | "task_run" | "version";
  targetId: string;
  /** "omission" = a test gap found after execution */
  kind?: "correction" | "omission";
  label?: string;
  placeholder?: string;
}

/** Correction / missed-test entry: the text is stored verbatim, then the agent turns it into memories or a new prompt version automatically (no review needed). */
export function CorrectionButton({ targetType, targetId, kind, label, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const omission = kind === "omission";
  const key = ["corrections", targetId];
  const list = useQuery({
    queryKey: key,
    queryFn: () => api<Correction[]>("/corrections", { params: { target_id: targetId } }),
    enabled: open,
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === "pending" || c.status === "processing") ? 3000 : false),
  });
  const save = useApiMutation(
    () => api("/corrections", { method: "POST", body: { target_type: targetType, target_id: targetId, content: text, ...(kind ? { kind } : {}) } }),
    { invalidate: [key, ["corrections"]], success: "文本已保存；Agent 会在后台处理，后续生成将使用它", onSuccess: () => setText("") },
  );
  const title = label || (omission ? "报告漏测" : "纠正");
  return (
    <>
      <Button onClick={() => setOpen(true)}>{title}</Button>
      <Modal
        title={omission ? "报告漏测：执行后发现但未被测试覆盖的问题" : "指出问题"}
        open={open}
        onCancel={() => setOpen(false)}
        okText={omission ? "提交漏测" : "提交纠正"}
        okButtonProps={{ disabled: !text.trim() }}
        confirmLoading={save.isPending}
        onOk={() => save.mutate()}
        width={640}
      >
        <Input.TextArea
          aria-label="纠正"
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={placeholder || (omission ? "例如：这次没有测试审批人审批自己提交的采购订单" : "例如：边界值应包含 0.01 和最大金额；预期结果应写明提示文案")}
        />
        <Typography.Text type="secondary">文本会原文保存；结果（记忆 / 新的提示词版本）可在“Agent 工具”页查看、停用或回滚。</Typography.Text>
        <Typography.Title level={5} style={{ marginTop: 16 }}>
          历史
        </Typography.Title>
        <ListSection label="纠正历史" count={list.data?.length} error={list.isError} onRetry={() => list.refetch()} recordLimit={200}>
        <List
          size="small"
          dataSource={list.data || []}
          locale={{ emptyText: "暂无" }}
          renderItem={(c) => (
            <List.Item>
              <Space direction="vertical" size={2} style={{ width: "100%" }}>
                <Space>
                  <CorrectionStatusTag status={c.status} />
                  {c.kind === "omission" && <Tag color="orange">漏测</Tag>}
                  <Typography.Text type="secondary">{fmtTime(c.created_at)}</Typography.Text>
                </Space>
                <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{c.content}</Typography.Paragraph>
                {c.status === "failed" && c.error && <Typography.Text type="danger">{c.error}</Typography.Text>}
              </Space>
            </List.Item>
          )}
        />
        </ListSection>
      </Modal>
    </>
  );
}
