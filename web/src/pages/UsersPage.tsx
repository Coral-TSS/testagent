import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import { useAuth } from "../app/AuthGate";

export interface UserRow {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "member";
  is_active: boolean;
  must_change_password: boolean;
  locked: boolean;
  has_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

const ROLE_OPTIONS = [
  { value: "member", label: "成员" },
  { value: "admin", label: "管理员" },
];

/** Admin: platform accounts (create, role, reset password, unlock, disable). */
export function UsersPage() {
  const { me } = useAuth();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/users"), enabled: me?.role === "admin" });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<UserRow | null>(null);
  const [createForm] = Form.useForm();
  const [resetForm] = Form.useForm();
  const create = useApiMutation((body: Record<string, unknown>) => api<UserRow>("/users", { method: "POST", body }), {
    invalidate: [["users"]],
    success: "账号已创建：用户首次登录时必须设置新密码",
  });
  const patch = useApiMutation(({ id, body }: { id: string; body: Record<string, unknown> }) => api<UserRow>(`/users/${id}`, { method: "PATCH", body }), {
    invalidate: [["users"]],
    success: "已保存",
  });

  if (me && me.role !== "admin") {
    return <Alert type="warning" showIcon title="只有管理员可以管理账号。" />;
  }
  return (
    <Card>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          用户 {users.data ? `(${users.data.length})` : ""}
        </Typography.Title>
        <Button type="primary" onClick={() => setCreating(true)}>
          新建用户
        </Button>
      </Space>
      <ListTable<UserRow>
        label="用户"
        error={users.isError}
        onRetry={() => users.refetch()}
        rowKey="id"
        loading={users.isLoading}
        dataSource={users.data}

        columns={[
          {
            title: "用户名",
            dataIndex: "username",
            render: (v: string, u) => (
              <Space>
                {v}
                {u.id === me?.id && <Tag>我</Tag>}
              </Space>
            ),
          },
          { title: "显示名", dataIndex: "display_name" },
          {
            title: "角色",
            dataIndex: "role",
            render: (v: string, u) => (
              <Select
                size="small"
                style={{ width: 110 }}
                value={v}
                disabled={u.id === me?.id}
                options={ROLE_OPTIONS}
                onChange={(role) => patch.mutate({ id: u.id, body: { role } })}
              />
            ),
          },
          {
            title: "状态",
            render: (_, u) => (
              <Space size={4} wrap>
                {u.is_active ? <Tag color="green">启用</Tag> : <Tag>已停用</Tag>}
                {u.locked && <Tag color="red">已锁定</Tag>}
                {u.must_change_password && <Tag color="orange">必须修改密码</Tag>}
              </Space>
            ),
          },
          { title: "上次登录", dataIndex: "last_login_at", render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—") },
          {
            title: "动作",
            render: (_, u) => (
              <Space size={4} wrap>
                <Button size="small" onClick={() => setResetting(u)}>
                  重置密码
                </Button>
                {u.locked && (
                  <Button size="small" onClick={() => patch.mutate({ id: u.id, body: { unlock: true } })}>
                    解锁
                  </Button>
                )}
                {u.id !== me?.id &&
                  (u.is_active ? (
                    <Popconfirm title={`停用 ${u.username}？该用户将在所有登录处退出。`} onConfirm={() => patch.mutate({ id: u.id, body: { is_active: false } })}>
                      <Button size="small" danger>
                        停用
                      </Button>
                    </Popconfirm>
                  ) : (
                    <Button size="small" onClick={() => patch.mutate({ id: u.id, body: { is_active: true } })}>
                      启用
                    </Button>
                  ))}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="新建用户"
        open={creating}
        okText="创建"
        confirmLoading={create.isPending}
        onCancel={() => setCreating(false)}
        onOk={() =>
          createForm.validateFields().then((v) =>
            create.mutate(v, {
              onSuccess: () => {
                setCreating(false);
                createForm.resetFields();
              },
            }),
          )
        }
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" initialValues={{ role: "member" }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }, { pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$/, message: "2–32 个字母、数字、. _ -" }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item name="password" label="初始密码（至少 10 个字符）" rules={[{ required: true }, { min: 10, message: "至少 10 个字符" }]} extra="请当面告知该用户；他们必须在首次登录时修改。">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`重置密码：${resetting?.username || ""}`}
        open={Boolean(resetting)}
        okText="重置"
        confirmLoading={patch.isPending}
        onCancel={() => setResetting(null)}
        onOk={() =>
          resetForm.validateFields().then((v) =>
            patch.mutate(
              { id: resetting!.id, body: { password: v.password } },
              {
                onSuccess: () => {
                  setResetting(null);
                  resetForm.resetFields();
                },
              },
            ),
          )
        }
        destroyOnHidden
      >
        <Form form={resetForm} layout="vertical">
          <Form.Item name="password" label="新的初始密码" rules={[{ required: true }, { min: 10, message: "至少 10 个字符" }]} extra="该用户已在各处退出，下次登录时必须修改密码。">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
