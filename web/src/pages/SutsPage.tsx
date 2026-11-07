import { ListTable } from "../components/ListView";
import { PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Form, Input, Modal, Popconfirm, Space, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Schemas, Sut } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { SutExplainer } from "../components/SutExplainer";

/** P01 SUT list */
export function SutsPage() {
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<Schemas["SutIn"]>();
  const create = useApiMutation((body: Schemas["SutIn"]) => api<Sut>("/suts", { method: "POST", body }), {
    invalidate: [["suts"]],
    success: "Created",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  const remove = useApiMutation((id: string) => api(`/suts/${id}`, { method: "DELETE" }), {
    invalidate: [["suts"]],
    success: "Deleted",
  });

  return (
    <>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          SUT
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          New SUT
        </Button>
      </Space>
      <SutExplainer closable={Boolean(suts.data?.length)} />
      <ListTable<Sut>
        label="SUTs"
        error={suts.isError}
        onRetry={() => suts.refetch()}
        rowKey="id"
        loading={suts.isLoading}
        dataSource={suts.data}

        locale={{
          emptyText: (
            <EmptyState
              title="No SUT yet"
              hint="Register the software to test first: enter a code and a name, then add an environment (its address) and build the model."
              actionLabel="New SUT"
              onAction={() => setOpen(true)}
            />
          ),
        }}
        columns={[
          { title: "Name (code)", dataIndex: "name", render: (name, row) => <Link to={`/suts/${row.id}`}>{`${name} (${row.code})`}</Link> },
          { title: "description", dataIndex: "description" },
          {
            title: "Action",
            width: 200,
            render: (_, row) => (
              <Space>
                <Link to={`/suts/${row.id}/model`}>Model</Link>
                <Link to={`/suts/${row.id}/review`}>Review</Link>
                <Popconfirm title="Delete this SUT?" onConfirm={() => remove.mutate(row.id)}>
                  <a>Delete</a>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="New SUT"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item
            name="code"
            label="Code"
            rules={[{ required: true, pattern: /^[A-Za-z][A-Za-z0-9_-]{0,63}$/, message: "Starts with a letter; digits, - and _ allowed" }]}
          >
            <Input placeholder="e.g. procurement" />
          </Form.Item>
          <Form.Item name="name" label="Name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="description">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
