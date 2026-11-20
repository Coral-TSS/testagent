import { ListTable, listTitle } from "../components/ListView";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, DatePicker, Form, InputNumber, Select, Space, Tabs, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { PersonStat, RequirementStat, SeverityWeights, Sut, Version } from "../api/types";
import { SEVERITY } from "../components/DefectTags";
import { ByRole, RequirementStatsTable, fmtScore } from "../components/StatsTables";

const SORT: Record<string, string> = {
  attributed_score: "按加权分",
  attributed_count: "按已归因缺陷",
  related_count: "按相关缺陷",
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
    success: "权重已保存；新的统计和报告将使用它们",
    onSuccess: () => qc.invalidateQueries({ queryKey: ["severity-weights"] }).then(() => qc.invalidateQueries({ queryKey: ["stats"] })),
  });
  return (
    <Card title="严重级别权重" size="small" style={{ marginBottom: 16 }} loading={q.isLoading}>
      <Form form={form} layout="inline" onFinish={(v) => save.mutate(v)}>
        {Object.entries(SEVERITY).map(([k, [label]]) => (
          <Form.Item key={k} name={k} label={label} rules={[{ required: true, message: "必填" }]}>
            <InputNumber min={0} max={1000} style={{ width: 80 }} />
          </Form.Item>
        ))}
        <Form.Item>
          <Space>
            <Button htmlType="submit" loading={save.isPending}>
              保存权重
            </Button>
            <Button type="link" disabled={!defaults.data} onClick={() => defaults.data && form.setFieldsValue(defaults.data)}>
              填入默认值
            </Button>
          </Space>
        </Form.Item>
      </Form>
      <Typography.Text type="secondary">加权分 = 各缺陷严重级别权重之和{defaults.data ? `（默认 ${Object.entries(SEVERITY).map(([k, [l]]) => `${l} ${defaults.data[k]}`).join(" / ")}）` : ""}；已拒绝的缺陷不计入。已生成的报告沿用生成时的权重。</Typography.Text>
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
      <Card title="人员统计">
        <Space wrap style={{ marginBottom: 12 }}>
          <Select allowClear placeholder="被测系统" style={{ width: 150 }} value={sutId} onChange={(v) => update({ sut_id: v, version_id: undefined })} options={(suts.data || []).map((s) => ({ value: s.id, label: s.code }))} />
          <Select allowClear placeholder="版本" style={{ width: 130 }} disabled={!sutId} value={versionId} onChange={(v) => update({ version_id: v })} options={(versions.data || []).map((v) => ({ value: v.id, label: v.name }))} />
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
              label: listTitle("人员排行", people.data?.length),
              children: (
                <ListTable<PersonStat>
                  label="人员排行"
                  error={people.isError}
                  onRetry={() => people.refetch()}
                  size="small"
                  rowKey="person_id"
                  loading={people.isLoading}
                  dataSource={people.data}

                  locale={{ emptyText: "范围内没有已归因或相关缺陷" }}
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
                      title: "人员",
                      dataIndex: "name",
                      render: (v: string, p) => (
                        <Space>
                          <Link to={drill(p.person_id)}>{v}</Link>
                          {!p.active && <Tag>已停用</Tag>}
                        </Space>
                      ),
                    },
                    { title: "已归因缺陷", dataIndex: "attributed_count", width: 90 },
                    { title: "加权分", dataIndex: "attributed_score", width: 80, render: fmtScore },
                    { title: "按角色（数量/加权分）", dataIndex: "attributed_by_role", render: (v: PersonStat["attributed_by_role"]) => <ByRole value={v} /> },
                    { title: "相关缺陷", dataIndex: "related_count", width: 90 },
                    { title: "", key: "drill", width: 90, render: (_: unknown, p) => <Link to={drill(p.person_id)}>查看缺陷</Link> },
                  ]}
                />
              ),
            },
            {
              key: "requirements",
              label: listTitle("各需求的缺陷密度", reqs.data?.length),
              children: <RequirementStatsTable rows={reqs.data} loading={reqs.isLoading} error={reqs.isError} onRetry={() => reqs.refetch()} />,
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          已归因：缺陷按原因类别归到负责人（需求/设计 → 需求负责人，开发 → 开发人员，测试 → 测试人员；环境和原因未定的不归因）。相关：在缺陷所属需求上担任任一角色。密度 = 缺陷数 ÷ 已执行用例数。
        </Typography.Paragraph>
      </Card>
    </>
  );
}
