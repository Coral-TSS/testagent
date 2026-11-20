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
    success: "已创建",
    onSuccess: () => {
      setOpen(false);
      form.resetFields();
    },
  });
  const remove = useApiMutation((id: string) => api(`/suts/${id}`, { method: "DELETE" }), {
    invalidate: [["suts"]],
    success: "已删除",
  });

  return (
    <>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          被测系统
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
          新建被测系统
        </Button>
      </Space>
      <SutExplainer closable={Boolean(suts.data?.length)} />
      <ListTable<Sut>
        label="被测系统"
        error={suts.isError}
        onRetry={() => suts.refetch()}
        rowKey="id"
        loading={suts.isLoading}
        dataSource={suts.data}

        locale={{
          emptyText: (
            <EmptyState
              title="暂无被测系统"
              hint="请先登记要测试的软件：输入编号和名称，然后添加环境（地址）并构建模型。"
              actionLabel="新建被测系统"
              onAction={() => setOpen(true)}
            />
          ),
        }}
        columns={[
          { title: "名称（编号）", dataIndex: "name", render: (name, row) => <Link to={`/suts/${row.id}`}>{`${name} (${row.code})`}</Link> },
          { title: "描述", dataIndex: "description" },
          {
            title: "动作",
            width: 200,
            render: (_, row) => (
              <Space>
                <Link to={`/suts/${row.id}/model`}>模型</Link>
                <Link to={`/suts/${row.id}/review`}>评审</Link>
                <Popconfirm title="要删除该被测系统吗？" onConfirm={() => remove.mutate(row.id)}>
                  <a>删除</a>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="新建被测系统"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={create.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
          <Form.Item
            name="code"
            label="编号"
            rules={[{ required: true, pattern: /^[A-Za-z][A-Za-z0-9_-]{0,63}$/, message: "以字母开头；允许数字、- 和 _" }]}
          >
            <Input placeholder="例如 procurement" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
