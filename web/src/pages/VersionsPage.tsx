import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Form, Input, Modal, Space, Table, Typography } from "antd";
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
    success: "Version created",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  return (
    <Card>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Version
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          New version
        </Button>
      </Space>
      <Table<Version>
        rowKey="id"
        loading={versions.isLoading}
        dataSource={versions.data}
        pagination={false}
        locale={{
          emptyText: (
            <EmptyState
              title="No version yet"
              hint="A version is a batch of requirements to test: new version → enter and confirm requirements → freeze → strategy, tasks, cases → run → defects and reports."
              actionLabel="New version"
              onAction={() => setOpen(true)}
            />
          ),
        }}
        columns={[
          { title: "Version", dataIndex: "name", render: (n, v) => <Link to={`/versions/${v.id}`}>{n}</Link> },
          { title: "Status", dataIndex: "status", render: (s) => <VersionStatusTag status={s} /> },
          { title: "Requirements", dataIndex: "requirement_count" },
          { title: "Frozen at", dataIndex: "frozen_at", render: (t: string | null) => fmtTime(t, { seconds: true }) },
        ]}
      />
      <Modal title="New version" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={create.isPending} forceRender>
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="Version name" rules={[{ required: true }]}>
            <Input placeholder="e.g. v1.0" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
