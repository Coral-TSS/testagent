import { ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Card, Form, Input, Switch, Tag, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Person } from "../api/types";
import { SimpleCrud } from "../components/SimpleCrud";

const ROLE: Record<string, string> = { owner: "Owner", developer: "Developer", tester: "Tester" };

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
      label="Person requirements"
      error={q.isError}
      onRetry={() => q.refetch()}
      size="small"
      rowKey="id"
      loading={q.isLoading}
      dataSource={q.data}

      locale={{ emptyText: "Not responsible for any requirement yet" }}
      columns={[
        { title: "System", dataIndex: "sut_code" },
        { title: "Version", dataIndex: "version_name", render: (v, r) => <Link to={`/versions/${r.version_id}`}>{v}</Link> },
        { title: "Requirement", render: (_, r) => `${r.code} ${r.title}` },
        { title: "Role", dataIndex: "roles", render: (roles: string[]) => roles.map((x) => <Tag key={x}>{ROLE[x] || x}</Tag>) },
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
    success: "Saved",
  });
  const update = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/persons/${id}`, { method: "PATCH", body }),
    { invalidate: [["persons"]], success: "Saved" },
  );
  const deactivate = useApiMutation((id: string) => api(`/persons/${id}/deactivate`, { method: "POST" }), {
    invalidate: [["persons"]],
    success: "Disabled",
  });
  return (
    <Card extra={<Link to="/stats/people">People stats & ranking</Link>}>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Person
      </Typography.Title>
      <div style={{ marginBottom: 8 }}>
        <Switch checked={onlyActive} onChange={setOnlyActive} /> Active only
      </div>
      <SimpleCrud<Person>
        total={allPersons.data?.length}
        filtered={onlyActive}
        error={persons.isError || allPersons.isError}
        onRetry={() => { persons.refetch(); if (onlyActive) allPersons.refetch(); }}
        title="Person"
        emptyTitle="No people yet"
        emptyHint="Register product, development and test people, assign owners on requirements by role; defects are attributed to people through requirements."
        rows={persons.data}
        loading={persons.isLoading}
        expandable={{ expandedRowRender: (p) => <PersonRequirements personId={p.id} /> }}
        columns={[
          { title: "Name", dataIndex: "name" },
          { title: "Title", dataIndex: "title" },
          { title: "Email", dataIndex: "email" },
          { title: "Status", dataIndex: "active", render: (a) => (a ? <Tag color="green">Active</Tag> : <Tag>Disabled</Tag>) },
        ]}
        fields={
          <>
            <Form.Item name="name" label="Name" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="title" label="Title">
              <Input />
            </Form.Item>
            <Form.Item name="email" label="Email" rules={[{ type: "email" }]}>
              <Input />
            </Form.Item>
          </>
        }
        onCreate={(v) => create.mutateAsync(v)}
        onUpdate={(row, v) => update.mutateAsync({ id: row.id, body: v })}
        extraActions={(row) => row.active ? <a onClick={() => deactivate.mutate(row.id)}>Deactivate</a> : <a onClick={() => update.mutate({ id: row.id, body: { active: true } })}>Enable</a>}
      />
    </Card>
  );
}
