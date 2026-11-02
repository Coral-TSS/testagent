import { useQuery } from "@tanstack/react-query";
import { Alert, App, Button, Card, Form, List, Popconfirm, Select, Space, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { CaseCategory, Requirement, TaskDetail, TaskSelector } from "../api/types";
import { CATEGORY_COLOR, CATEGORY_LABEL, SCENARIO_LABEL, categoryOptions, cleanSelector, describeSelector, qualityTagOptions } from "../utils/categories";
import { fmtTime } from "../utils/time";

interface PreviewCase {
  id: string;
  code: string;
  title: string;
  category: CaseCategory;
  reason: string;
  excluded: boolean;
}

/** the task's case rule — preview, save, sync, and cases a person took out. */
export function TaskRuleCard({ task, editable, onChanged }: { task: TaskDetail; editable: boolean; onChanged: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<TaskSelector>();
  const [preview, setPreview] = useState<PreviewCase[] | null>(null);
  const reqs = useQuery({
    queryKey: ["requirements", task.version_id],
    queryFn: () => api<Requirement[]>(`/versions/${task.version_id}/requirements`),
  });
  useEffect(() => {
    form.setFieldsValue({ requirement_ids: [], categories: [], priorities: [], scenarios: [], quality_tags: [], ...(task.selector || {}) });
  }, [task.selector, form]);
  const reqCode = (id: string) => reqs.data?.find((r) => r.id === id)?.code || id;
  const body = () => ({ selector: cleanSelector(form.getFieldsValue()) });
  const runPreview = useApiMutation(() => api<{ cases: PreviewCase[] }>(`/tasks/${task.id}/selector/preview`, { method: "POST", body: body() }), {
    onSuccess: (out) => setPreview(out.cases),
  });
  const save = useApiMutation((selector: TaskSelector | null) => api(`/tasks/${task.id}/selector`, { method: "PUT", body: { selector } }), {
    success: "Rule saved; cases synced to the rule",
    onSuccess: () => {
      setPreview(null);
      onChanged();
    },
  });
  const sync = useApiMutation(() => api<{ added: string[]; removed: string[] }>(`/tasks/${task.id}/sync`, { method: "POST" }), {
    onSuccess: (out) => {
      message.success(out.added.length || out.removed.length ? `Synced: added ${out.added.join(", ") || "None"}; removed ${out.removed.join(", ") || "None"}` : "Already up to date, no change");
      onChanged();
    },
  });
  const restore = useApiMutation((caseId: string) => api(`/tasks/${task.id}/exclusions/${caseId}`, { method: "DELETE" }), { success: "Restored; it will be added again when the rule matches", onSuccess: onChanged });
  const stats = task.rule_stats;
  return (
    <Card size="small" title="Case selection rule" style={{ marginBottom: 16 }} data-testid="task-rule">
      <Typography.Paragraph style={{ marginBottom: 8 }}>
        Current rule: <b data-testid="rule-text">{describeSelector(task.selector, reqCode)}</b>
      </Typography.Paragraph>
      {stats && (
        <Typography.Paragraph type="secondary" data-testid="rule-stats">
          By rule {stats.rule} · added manually {stats.manual} · removed manually {stats.excluded}. Cases join tasks with a matching rule automatically when set “Ready” (not while the task is running or archived); cases removed by hand are not added back by the rule, and cases added by hand are not removed by it.
        </Typography.Paragraph>
      )}
      <Form form={form} layout="vertical" disabled={!editable}>
        <Space wrap align="start">
          <Form.Item name="requirement_ids" label="Requirement">
            <Select mode="multiple" style={{ minWidth: 220 }} optionFilterProp="label" options={(reqs.data || []).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))} />
          </Form.Item>
          <Form.Item name="categories" label="Case category">
            <Select mode="multiple" style={{ minWidth: 200 }} options={categoryOptions} />
          </Form.Item>
          <Form.Item name="priorities" label="Priority">
            <Select mode="multiple" style={{ minWidth: 120 }} options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="scenarios" label="Scenario">
            <Select mode="multiple" style={{ minWidth: 140 }} options={Object.entries(SCENARIO_LABEL).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="quality_tags" label="Quality attributes">
            <Select mode="tags" style={{ minWidth: 160 }} options={qualityTagOptions} />
          </Form.Item>
        </Space>
        <Space wrap>
          <Button onClick={() => runPreview.mutate(undefined)} loading={runPreview.isPending}>
            Preview matches
          </Button>
          <Button type="primary" onClick={() => save.mutate(body().selector)} loading={save.isPending}>
            Save rule and sync
          </Button>
          {task.selector && (
            <Button onClick={() => sync.mutate(undefined)} loading={sync.isPending}>
              Sync now
            </Button>
          )}
          {task.selector && (
            <Popconfirm title="Clear the rule? Existing cases stay; afterwards cases can only be added by hand." onConfirm={() => save.mutate(null)}>
              <Button>Clear rule</Button>
            </Popconfirm>
          )}
        </Space>
      </Form>
      {preview && (
        <Table<PreviewCase>
          style={{ marginTop: 12 }}
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={preview}
          title={() => `The rule matches ${preview.length} ready case(s)${preview.some((c) => c.excluded) ? " (those marked “removed manually” are not added)" : ""}`}
          locale={{ emptyText: "No matching ready cases" }}
          columns={[
            { title: "Case", render: (_: unknown, c) => <Link to={`/cases/${c.id}`}>{`${c.title} (${c.code})`}</Link> },
            { title: "category", dataIndex: "category", render: (c: CaseCategory) => <Tag color={CATEGORY_COLOR[c]}>{CATEGORY_LABEL[c]}</Tag> },
            { title: "Reason", dataIndex: "reason" },
            { title: "", dataIndex: "excluded", render: (x: boolean) => (x ? <Tag>Removed manually</Tag> : null) },
          ]}
        />
      )}
      {(task.exclusions?.length ?? 0) > 0 && (
        <>
          <Alert style={{ marginTop: 12 }} type="info" showIcon title="Cases removed by hand (the rule will not add them back)" />
          <List
            size="small"
            dataSource={task.exclusions}
            renderItem={(e) => (
              <List.Item actions={editable ? [<a key="restore" onClick={() => restore.mutate(e.case_id)}>Restore</a>] : []}>
                <Link to={`/cases/${e.case_id}`}>{`${e.title} (${e.code})`}</Link>
                <Typography.Text type="secondary">
                  {e.removed_by} at {fmtTime(e.created_at)} Remove
                </Typography.Text>
              </List.Item>
            )}
          />
        </>
      )}
    </Card>
  );
}
