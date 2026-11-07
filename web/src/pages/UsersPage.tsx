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
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
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
    success: "Account created: the user must choose a new password at first sign-in",
  });
  const patch = useApiMutation(({ id, body }: { id: string; body: Record<string, unknown> }) => api<UserRow>(`/users/${id}`, { method: "PATCH", body }), {
    invalidate: [["users"]],
    success: "Saved",
  });

  if (me && me.role !== "admin") {
    return <Alert type="warning" showIcon title="Only an admin can manage accounts." />;
  }
  return (
    <Card>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Users {users.data ? `(${users.data.length})` : ""}
        </Typography.Title>
        <Button type="primary" onClick={() => setCreating(true)}>
          New user
        </Button>
      </Space>
      <ListTable<UserRow>
        label="Users"
        error={users.isError}
        onRetry={() => users.refetch()}
        rowKey="id"
        loading={users.isLoading}
        dataSource={users.data}

        columns={[
          {
            title: "User name",
            dataIndex: "username",
            render: (v: string, u) => (
              <Space>
                {v}
                {u.id === me?.id && <Tag>you</Tag>}
              </Space>
            ),
          },
          { title: "Display name", dataIndex: "display_name" },
          {
            title: "Role",
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
            title: "Status",
            render: (_, u) => (
              <Space size={4} wrap>
                {u.is_active ? <Tag color="green">active</Tag> : <Tag>disabled</Tag>}
                {u.locked && <Tag color="red">locked</Tag>}
                {u.must_change_password && <Tag color="orange">must change password</Tag>}
              </Space>
            ),
          },
          { title: "Last sign-in", dataIndex: "last_login_at", render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—") },
          {
            title: "Action",
            render: (_, u) => (
              <Space size={4} wrap>
                <Button size="small" onClick={() => setResetting(u)}>
                  Reset password
                </Button>
                {u.locked && (
                  <Button size="small" onClick={() => patch.mutate({ id: u.id, body: { unlock: true } })}>
                    Unlock
                  </Button>
                )}
                {u.id !== me?.id &&
                  (u.is_active ? (
                    <Popconfirm title={`Disable ${u.username}? They are signed out everywhere.`} onConfirm={() => patch.mutate({ id: u.id, body: { is_active: false } })}>
                      <Button size="small" danger>
                        Disable
                      </Button>
                    </Popconfirm>
                  ) : (
                    <Button size="small" onClick={() => patch.mutate({ id: u.id, body: { is_active: true } })}>
                      Enable
                    </Button>
                  ))}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title="New user"
        open={creating}
        okText="Create"
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
          <Form.Item name="username" label="User name" rules={[{ required: true }, { pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$/, message: "2–32 letters, digits, . _ -" }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="Display name">
            <Input />
          </Form.Item>
          <Form.Item name="role" label="Role">
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item name="password" label="Initial password (at least 10 characters)" rules={[{ required: true }, { min: 10, message: "At least 10 characters" }]} extra="Tell the user in person; they must change it at first sign-in.">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`Reset password: ${resetting?.username || ""}`}
        open={Boolean(resetting)}
        okText="Reset"
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
          <Form.Item name="password" label="New initial password" rules={[{ required: true }, { min: 10, message: "At least 10 characters" }]} extra="The user is signed out everywhere and must change it at the next sign-in.">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
