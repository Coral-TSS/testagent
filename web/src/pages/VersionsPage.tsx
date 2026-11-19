import { ListTable } from "../components/ListView";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Form, Input, Modal, Space, Typography } from "antd";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Version } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { VersionStatusTag } from "../components/StatusTags";
import { fmtTime } from "../utils/time";

/** P05 version list */
export function VersionsPage() {
  const { sutId = "" } = useParams();
  const versions = useQuery({ queryKey: ["versions", sutId], queryFn: () => api<Version[]>(`/suts/${sutId}/versions`) });
  const [search] = useSearchParams();
  const [open, setOpen] = useState(search.get("new") === "1");
  const [form] = Form.useForm();
  const create = useApiMutation((body: { name: string }) => api(`/suts/${sutId}/versions`, { method: "POST", body }), {
    invalidate: [["versions", sutId]],
    success: "版本已创建",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  return (
    <Card>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          版本
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          新建版本
        </Button>
      </Space>
      <ListTable<Version>
        label="版本"
        error={versions.isError}
        onRetry={() => versions.refetch()}
        rowKey="id"
        loading={versions.isLoading}
        dataSource={versions.data}

        locale={{
          emptyText: (
            <EmptyState
              title="暂无版本"
              hint="版本是一批待测需求：新建版本 → 录入并确认需求 → 冻结 → 策略、任务、用例 → 执行 → 缺陷与报告。"
              actionLabel="新建版本"
              onAction={() => setOpen(true)}
            />
          ),
        }}
        columns={[
          { title: "版本", dataIndex: "name", render: (n, v) => <Link to={`/versions/${v.id}`}>{n}</Link> },
          { title: "状态", dataIndex: "status", render: (s) => <VersionStatusTag status={s} /> },
          { title: "需求", dataIndex: "requirement_count" },
          { title: "冻结于", dataIndex: "frozen_at", render: (t: string | null) => fmtTime(t, { seconds: true }) },
        ]}
      />
      <Modal title="新建版本" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={create.isPending} forceRender>
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="版本名称" rules={[{ required: true }]}>
            <Input placeholder="例如 v1.0" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
