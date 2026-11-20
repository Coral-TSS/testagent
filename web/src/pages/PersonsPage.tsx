import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Form, Input, Switch, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Person } from "../api/types";
import { SimpleCrud } from "../components/SimpleCrud";

const ROLE: Record<string, string> = { owner: "负责人", developer: "开发", tester: "测试" };

interface PersonReq {
  id: string;
  code: string;
  title: string;
  status: string;
  version_id: string;
  version_name: string;
  sut_code: string;
  roles: string[];
}

function PersonRequirements({ personId }: { personId: string }) {
  const q = useQuery({
    queryKey: ["person-reqs", personId],
    queryFn: () => api<PersonReq[]>(`/persons/${personId}/requirements`),
  });
  return (
    <ListTable<PersonReq>
      label="人员负责的需求"
      error={q.isError}
      onRetry={() => q.refetch()}
      size="small"
      rowKey="id"
      loading={q.isLoading}
      dataSource={q.data}

      locale={{ emptyText: "尚未负责任何需求" }}
      columns={[
        { title: "系统", dataIndex: "sut_code" },
        { title: "版本", dataIndex: "version_name", render: (v, r) => <Link to={`/versions/${r.version_id}`}>{v}</Link> },
        { title: "需求", render: (_, r) => `${r.code} ${r.title}` },
        { title: "角色", dataIndex: "roles", render: (roles: string[]) => roles.map((x) => <Tag key={x}>{ROLE[x] || x}</Tag>) },
      ]}
    />
  );
}

/** P13 people (simple people management; trace owners by requirement) */
export function PersonsPage() {
  const [onlyActive, setOnlyActive] = useState(false);
  const persons = useQuery({
    queryKey: ["persons", onlyActive],
    queryFn: () => api<Person[]>("/persons", { params: { active: onlyActive ? true : undefined } }),
  });
  const allPersons = useQuery({ queryKey: ["persons", false], queryFn: () => api<Person[]>("/persons") });
  const create = useApiMutation((body: Record<string, unknown>) => api("/persons", { method: "POST", body }), {
    invalidate: [["persons"]],
    success: "已保存",
  });
  const update = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/persons/${id}`, { method: "PATCH", body }),
    { invalidate: [["persons"]], success: "已保存" },
  );
  const deactivate = useApiMutation((id: string) => api(`/persons/${id}/deactivate`, { method: "POST" }), {
    invalidate: [["persons"]],
    success: "已停用",
  });
  return (
    <Card extra={<Link to="/stats/people">人员统计与排行</Link>}>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        人员
      </Typography.Title>
      <div style={{ marginBottom: 8 }}>
        <Switch checked={onlyActive} onChange={setOnlyActive} /> 仅显示在职
      </div>
      <SimpleCrud<Person>
        total={allPersons.data?.length}
        filtered={onlyActive}
        error={persons.isError || allPersons.isError}
        onRetry={() => { persons.refetch(); if (onlyActive) allPersons.refetch(); }}
        title="人员"
        emptyTitle="暂无人员"
        emptyHint="登记产品、开发和测试人员，按角色在需求上指定负责人；缺陷通过需求归因到人员。"
        rows={persons.data}
        loading={persons.isLoading}
        expandable={{ expandedRowRender: (p) => <PersonRequirements personId={p.id} /> }}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "标题", dataIndex: "title" },
          { title: "邮箱", dataIndex: "email" },
          { title: "状态", dataIndex: "active", render: (a) => (a ? <Tag color="green">正常</Tag> : <Tag>已停用</Tag>) },
        ]}
        fields={
          <>
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="title" label="标题">
              <Input />
            </Form.Item>
            <Form.Item name="email" label="邮箱" rules={[{ type: "email" }]}>
              <Input />
            </Form.Item>
          </>
        }
        onCreate={(v) => create.mutateAsync(v)}
        onUpdate={(row, v) => update.mutateAsync({ id: row.id, body: v })}
        extraActions={(row) => row.active ? <a onClick={() => deactivate.mutate(row.id)}>停用</a> : <a onClick={() => update.mutate({ id: row.id, body: { active: true } })}>启用</a>}
      />
    </Card>
  );
}
