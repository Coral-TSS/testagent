import { useQuery } from "@tanstack/react-query";
import { Button, Input, List, Modal, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Correction } from "../api/types";
import { fmtTime } from "../utils/time";
import { ListSection } from "./ListView";

export const CORRECTION_STATUS: Record<string, [string, string]> = {
  pending: ["Pending", "default"],
  processing: ["Processing", "processing"],
  processed: ["Processed", "green"],
  failed: ["Processing failed", "red"],
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
    { invalidate: [key, ["corrections"]], success: "Text saved; the agent processes it in the background and later generations will use it", onSuccess: () => setText("") },
  );
  const title = label || (omission ? "Report missed test" : "Correct");
  return (
    <>
      <Button onClick={() => setOpen(true)}>{title}</Button>
      <Modal
        title={omission ? "Report missed test: a problem found after execution that was not tested" : "Point out the problem"}
        open={open}
        onCancel={() => setOpen(false)}
        okText={omission ? "Submit missed test" : "Submit correction"}
        okButtonProps={{ disabled: !text.trim() }}
        confirmLoading={save.isPending}
        onOk={() => save.mutate()}
        width={640}
      >
        <Input.TextArea
          aria-label="Correction"
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={placeholder || (omission ? "e.g. This time we did not test an approver approving a purchase order they submitted" : "e.g. Boundary values should include 0.01 and the maximum amount; the expected result should state the message text")}
        />
        <Typography.Text type="secondary">The text is stored verbatim; results (memories / new prompt versions) can be viewed, disabled or rolled back on the “Agent tools” page.</Typography.Text>
        <Typography.Title level={5} style={{ marginTop: 16 }}>
          History
        </Typography.Title>
        <ListSection label="Correction history" count={list.data?.length} error={list.isError} onRetry={() => list.refetch()} recordLimit={200}>
        <List
          size="small"
          dataSource={list.data || []}
          locale={{ emptyText: "None yet" }}
          renderItem={(c) => (
            <List.Item>
              <Space direction="vertical" size={2} style={{ width: "100%" }}>
                <Space>
                  <CorrectionStatusTag status={c.status} />
                  {c.kind === "omission" && <Tag color="orange">Missed test</Tag>}
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
