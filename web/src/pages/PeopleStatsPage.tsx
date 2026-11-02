import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, DatePicker, Form, InputNumber, Select, Space, Table, Tabs, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { PersonStat, RequirementStat, SeverityWeights, Sut, Version } from "../api/types";
import { SEVERITY } from "../components/DefectTags";
import { ByRole, RequirementStatsTable, fmtScore } from "../components/StatsTables";

const SORT: Record<string, string> = {
  attributed_score: "By weighted score",
  attributed_count: "By attributed defects",
  related_count: "By related defects",
};

/** Severity weights: only affect statistics and reports generated afterwards (existing reports keep their weights) */
export function SeverityWeightsCard() {
  const qc = useQueryClient();
  const [form] = Form.useForm<SeverityWeights>();
  const q = useQuery({ queryKey: ["severity-weights"], queryFn: () => api<SeverityWeights>("/settings/severity-weights") });
  const defaults = useQuery({ queryKey: ["severity-weights-defaults"], queryFn: () => api<SeverityWeights>("/settings/severity-weights/defaults") });
  useEffect(() => {
    if (q.data) form.setFieldsValue(q.data);
  }, [q.data, form]);
  const save = useApiMutation((body: SeverityWeights) => api<SeverityWeights>("/settings/severity-weights", { method: "PUT", body }), {
    success: "Weights saved; new statistics and reports will use them",
    onSuccess: () => qc.invalidateQueries({ queryKey: ["severity-weights"] }).then(() => qc.invalidateQueries({ queryKey: ["stats"] })),
  });
  return (
    <Card title="Severity weights" size="small" style={{ marginBottom: 16 }} loading={q.isLoading}>
      <Form form={form} layout="inline" onFinish={(v) => save.mutate(v)}>
        {Object.entries(SEVERITY).map(([k, [label]]) => (
          <Form.Item key={k} name={k} label={label} rules={[{ required: true, message: "Required" }]}>
            <InputNumber min={0} max={1000} style={{ width: 80 }} />
          </Form.Item>
        ))}
        <Form.Item>
          <Space>
            <Button htmlType="submit" loading={save.isPending}>
              Save weights
            </Button>
            <Button type="link" disabled={!defaults.data} onClick={() => defaults.data && form.setFieldsValue(defaults.data)}>
              Fill in defaults
            </Button>
          </Space>
        </Form.Item>
      </Form>
      <Typography.Text type="secondary">Weighted score = sum of the severity weights of the defects{defaults.data ? ` (default ${Object.entries(SEVERITY).map(([k, [l]]) => `${l} ${defaults.data[k]}`).join(" / ")})` : ""}; rejected defects do not count. Generated reports keep the weights they were generated with.</Typography.Text>
    </Card>
  );
}

/** P13 people stats: attributed / related ranking, per role, drill down to defects; plus defect density per requirement */
export function PeopleStatsPage() {
  const [params, setParams] = useSearchParams();
  const sutId = params.get("sut_id") || undefined;
  const versionId = params.get("version_id") || undefined;
  const from = params.get("from") || undefined;
  const to = params.get("to") || undefined;
  const sort = params.get("sort") || "attributed_score";
  const tab = params.get("tab") || "people";
  const update = (changes: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next, { replace: true });
  };
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const versions = useQuery({
    queryKey: ["versions", sutId],
    queryFn: () => api<Version[]>(`/suts/${sutId}/versions`),
    enabled: Boolean(sutId),
  });
  const scope = { sut_id: sutId, version_id: versionId, from, to };
  const people = useQuery({
    queryKey: ["stats", "people", scope, sort],
    queryFn: () => api<PersonStat[]>("/stats/people", { params: { ...scope, sort } }),
  });
  const reqs = useQuery({
    queryKey: ["stats", "requirements", scope],
    queryFn: () => api<RequirementStat[]>("/stats/requirements", { params: scope }),
    enabled: tab === "requirements",
  });
  const drill = (personId: string) => {
    const q = new URLSearchParams({ person_id: personId });
    if (sutId) q.set("sut_id", sutId);
    if (versionId) q.set("version_id", versionId);
    return `/defects?${q.toString()}`;
  };
  return (
    <>
      <SeverityWeightsCard />
      <Card title="People stats">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select allowClear placeholder="SUT" style={{ width: 150 }} value={sutId} onChange={(v) => update({ sut_id: v, version_id: undefined })} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
          <Select allowClear placeholder="Version" style={{ width: 130 }} disabled={!sutId} value={versionId} onChange={(v) => update({ version_id: v })} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
          <DatePicker.RangePicker
            value={from && to ? [dayjs(from), dayjs(to)] : null}
            onChange={(r) =>
              update({
                from: r?.[0] ? r[0].startOf("day").toISOString() : undefined,
                to: r?.[1] ? r[1].endOf("day").toISOString() : undefined,
              })
            }
          />
          {tab === "people" && (
            <Select style={{ width: 140 }} value={sort} onChange={(v) => update({ sort: v === "attributed_score" ? undefined : v })} options={Object.entries(SORT).map(([value, label]) => ({ value, label }))} />
          )}
        </Space>
        <Tabs
          activeKey={tab}
          onChange={(k) => update({ tab: k === "people" ? undefined : k })}
          items={[
            {
              key: "people",
              label: "People ranking",
              children: (
                <Table<PersonStat>
                  size="small"
                  rowKey="person_id"
                  loading={people.isLoading}
                  dataSource={people.data || []}
                  pagination={false}
                  locale={{ emptyText: "No attributed or related defects in scope" }}
                  expandable={{
                    rowExpandable: (p) => p.requirements.length > 0,
                    expandedRowRender: (p) => (
                      <Space wrap>
                        {p.requirements.map((r) => (
                          <Tag key={r.code}>
                            {r.code} {r.title} · {r.count}
                          </Tag>
                        ))}
                      </Space>
                    ),
                  }}
                  columns={[
                    {
                      title: "Person",
                      dataIndex: "name",
                      render: (v: string, p) => (
                        <Space>
                          <Link to={drill(p.person_id)}>{v}</Link>
                          {!p.active && <Tag>Disabled</Tag>}
                        </Space>
                      ),
                    },
                    { title: "Attributed defects", dataIndex: "attributed_count", width: 90 },
                    { title: "Weighted score", dataIndex: "attributed_score", width: 80, render: fmtScore },
                    { title: "By role (count/weighted score)", dataIndex: "attributed_by_role", render: (v: PersonStat["attributed_by_role"]) => <ByRole value={v} /> },
                    { title: "Related defects", dataIndex: "related_count", width: 90 },
                    { title: "", key: "drill", width: 90, render: (_: unknown, p) => <Link to={drill(p.person_id)}>View defects</Link> },
                  ]}
                />
              ),
            },
            {
              key: "requirements",
              label: "Defect density per requirement",
              children: <RequirementStatsTable rows={reqs.data || []} loading={reqs.isLoading} />,
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          Attributed: defects are assigned to the responsible person by cause category (requirement/design → requirement owner, development → developer, test → tester; environment and undetermined are not attributed). Related: holds any role on the defect's requirement. Density = defects ÷ executed cases.
        </Typography.Paragraph>
      </Card>
    </>
  );
}
