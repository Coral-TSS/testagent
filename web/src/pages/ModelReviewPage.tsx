import { ListSection, ListTable } from "../components/ListView";
import { DownloadOutlined, PrinterOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Checkbox, Descriptions, Input, List, Progress, Segmented, Space, Statistic, Tag, Typography } from "antd";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, describeError, download } from "../api/client";
import type { DataType, ModelReview, ReviewCoverage, ReviewField, ReviewMark } from "../api/types";
import { DATA_TYPE_LABEL } from "../components/dataTypes";
import { objLabel } from "../components/ObjLink";

type Target = "entity" | "action" | "link";
type Filter = "all" | "todo" | "uncovered";

/** Who touches an element: requirements and cases, each as "Title (code)" links; uncovered highlighted. */
export function CoverageLine({ coverage, uncovered }: { coverage: ReviewCoverage; uncovered: boolean }) {
  if (uncovered) return <Tag color="orange">Not covered: no requirement or case links to it</Tag>;
  return (
    <Space wrap size={4}>
      {coverage.requirements.map((r) => (
        <Tag key={`r${r.id}`} color="blue">
          <Link to={`/versions/${r.version_id}?req=${r.id}`}>{objLabel(r.title, r.code)}</Link>
        </Tag>
      ))}
      {coverage.cases.map((c) => (
        <Tag key={`c${c.id}`} color="green">
          <Link to={`/cases/${c.id}`}>{objLabel(c.title, c.code)}</Link>
        </Tag>
      ))}
    </Space>
  );
}

function typeText(f: ReviewField) {
  const label = DATA_TYPE_LABEL[f.data_type as DataType] || f.data_type;
  if (f.enum_values?.length) return `${label} (${f.enum_values.join(" / ")})`;
  if (f.ref_node_name) return `${label} → ${f.ref_node_name}`;
  return label;
}

/** Read-only review page of a SUT's model with per-element "Reviewed" marks. */
export function ModelReviewPage() {
  const { sutId = "" } = useParams();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [filter, setFilter] = useState<Filter>("all");
  const review = useQuery({ queryKey: ["model-review", sutId], queryFn: () => api<ModelReview>(`/suts/${sutId}/model-review`) });

  const mark = async (target_type: Target, target_id: string, reviewed: boolean, note?: string | null) => {
    try {
      await api(`/suts/${sutId}/model-review/marks`, { method: "PUT", body: { target_type, target_id, reviewed, note: note || null } });
      qc.invalidateQueries({ queryKey: ["model-review", sutId] });
    } catch (err) {
      message.error(describeError(err));
    }
  };
  const exportMd = async () => {
    try {
      await download(`/suts/${sutId}/model-review.md`, {}, `model-review-${review.data?.sut.code || sutId}.md`);
    } catch (err) {
      message.error(describeError(err));
    }
  };

  const r = review.data;
  if (!r) return <Card loading={review.isLoading} />;
  const s = r.summary;
  const show = (e: { uncovered: boolean; mark?: ReviewMark | null }) =>
    filter === "all" || (filter === "uncovered" ? e.uncovered : !(e.mark?.reviewed && !e.mark.stale));

  const markBox = (type: Target, id: string, m?: ReviewMark | null) => (
    <Space size={4} className="no-print-hide">
      <Checkbox checked={Boolean(m?.reviewed)} onChange={(e) => mark(type, id, e.target.checked, m?.note)} aria-label="Reviewed">
        Reviewed
      </Checkbox>
      {m?.stale && <Tag color="red">Changed since review; please review again</Tag>}
    </Space>
  );
  const noteBox = (type: Target, id: string, m?: ReviewMark | null) =>
    m?.reviewed ? (
      <Input
        size="small"
        placeholder="Review note (optional, saved when you leave the box)"
        defaultValue={m.note || ""}
        onBlur={(e) => (e.target.value || null) !== (m.note || null) && mark(type, id, true, e.target.value)}
        style={{ maxWidth: 420 }}
      />
    ) : null;

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }} data-testid="model-review">
      <Card
        title={`Model review: ${objLabel(r.sut.name, r.sut.code)}`}
        extra={
          <Space>
            <Button icon={<DownloadOutlined />} onClick={exportMd}>
              Export Markdown
            </Button>
            <Button icon={<PrinterOutlined />} onClick={() => window.print()}>
              Print
            </Button>
            <Link to={`/suts/${sutId}/model`}>Edit on the model page</Link>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="Review checklist"
          description={
            <ol style={{ margin: 0, paddingInlineStart: 20 }}>
              <li>Entities: field names match the API/code fields; types, required flags and enum values are correct; no business object is missing.</li>
              <li>Links: both directions read naturally (e.g. PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder); cardinality and foreign keys are correct.</li>
              <li>Actions: the purpose is clear; inputs/outputs, bound APIs, preconditions and effects match the real system.</li>
              <li>Coverage: elements marked “Not covered” have no requirement or case yet; check whether a test is missing.</li>
              <li>“Reviewed” is only a review aid and does not accept any AI suggestion; suggestions still have to be accepted one by one under “Model suggestions” on the version page or “Links” on the model page.</li>
            </ol>
          }
        />
        <Space size={32} wrap>
          <Statistic title="Entities / fields" value={`${s.entities} / ${s.fields}`} />
          <Statistic title="Link" value={s.links} />
          <Statistic title="Actions" value={s.actions} />
          <div>
            <Typography.Text type="secondary">Reviewed</Typography.Text>
            <Progress percent={s.total ? Math.round((s.reviewed / s.total) * 100) : 0} format={() => `${s.reviewed}/${s.total}`} style={{ width: 180 }} />
          </div>
          <Statistic title="Changed since review" value={s.stale} styles={{ content: { color: s.stale ? "#cf1322" : undefined } }} />
          <Statistic title="Not covered" value={s.uncovered} styles={{ content: { color: s.uncovered ? "#d46b08" : undefined } }} />
          <Statistic
            title="Pending model suggestions"
            value={s.pending_suggestions}
            suffix={
              r.pending_by_source?.ai_inferred ? (
                <Typography.Text type="warning" style={{ fontSize: 12 }} data-testid="pending-ai">
                  {r.pending_by_source.ai_inferred} AI inferred
                </Typography.Text>
              ) : undefined
            }
          />
        </Space>
        <div style={{ marginTop: 12 }}>
          <Segmented<Filter>
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "todo", label: "Not reviewed" },
              { value: "uncovered", label: "Not covered" },
            ]}
          />
        </div>
      </Card>

      <Card title={`Entities (${r.entities.length})`}>
        <ListSection label="Review entities" count={r.entities.filter(show).length} total={r.entities.length} filtered={filter !== "all"}>
        {r.entities.length === 0 && <Typography.Text type="secondary">No entities yet; build the model on the model page first.</Typography.Text>}
        {r.entities.filter(show).map((e) => (
          <Card
            key={e.id}
            size="small"
            type="inner"
            style={{ marginBottom: 12 }}
            title={
              <Space>
                <Link to={`/suts/${sutId}/model?node=${e.id}`}>{e.name}</Link>
                {e.uncovered && <Tag color="orange">Not covered</Tag>}
              </Space>
            }
            extra={markBox("entity", e.id, e.mark)}
          >
            {e.description && <Typography.Paragraph>{e.description}</Typography.Paragraph>}
            <ListTable<ReviewField>
              pagination={false}
              scroll={{ y: "min(32vh, 320px)" }}
              label={`Fields of ${e.name}`}
              size="small"
              rowKey="id"

              dataSource={e.fields}
              locale={{ emptyText: "No fields registered" }}
              rowClassName={(f) => (f.uncovered ? "review-uncovered" : "")}
              columns={[
                { title: "Field (API name)", dataIndex: "name", render: (v: string) => <code>{v}</code> },
                { title: "Display name", dataIndex: "display_name", render: (v) => v || "-" },
                { title: "Type", render: (_, f) => typeText(f) },
                { title: "Required", dataIndex: "required", width: 60, render: (v: boolean) => (v ? "yes" : "no") },
                { title: "DB column name", dataIndex: "storage_name", render: (v) => v || "-" },
                { title: "description", dataIndex: "description", ellipsis: true },
                { title: "Coverage", render: (_, f) => <CoverageLine coverage={f.coverage} uncovered={f.uncovered} /> },
              ]}
            />
            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
              <Descriptions.Item label="Link">
                {e.relations.length ? (
                  <Space orientation="vertical" size={0}>
                    {e.relations.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </Space>
                ) : (
                  "None"
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Coverage">
                <CoverageLine coverage={e.coverage} uncovered={e.uncovered} />
              </Descriptions.Item>
            </Descriptions>
            {noteBox("entity", e.id, e.mark)}
          </Card>
        ))}
        </ListSection>
      </Card>

      <Card title={`Links (${r.links.length})`}>
        <ListSection label="Review links" count={r.links.filter(show).length} total={r.links.length} filtered={filter !== "all"}>
        <List
          size="small"
          dataSource={r.links.filter(show)}
          locale={{ emptyText: "No links; use “New link” on the model page, or accept the link suggestions generated from foreign-key fields" }}
          renderItem={(l) => (
            <List.Item actions={[markBox("link", l.id, l.mark)]}>
              <Space orientation="vertical" size={2}>
                <span>
                  <b>{l.forward}</b> / <b>{l.reverse}</b> <Tag color="purple">{l.cardinality}</Tag>
                  {l.fk_field && <Typography.Text type="secondary">foreign key {l.fk_field}</Typography.Text>}
                  {l.via_name && <Typography.Text type="secondary"> junction entity {l.via_name}</Typography.Text>}
                  {l.required && <Tag>Required</Tag>}
                  {l.api_names.length > 0 && <Typography.Text type="secondary"> API name {l.api_names.join(" / ")}</Typography.Text>}
                </span>
                {l.description && <Typography.Text type="secondary">{l.description}</Typography.Text>}
                <CoverageLine coverage={l.coverage} uncovered={l.uncovered} />
                {noteBox("link", l.id, l.mark)}
              </Space>
            </List.Item>
          )}
        />
        </ListSection>
      </Card>

      <Card title={`Actions (${r.actions.length})`}>
        <ListSection label="Review actions" count={r.actions.filter(show).length} total={r.actions.length} filtered={filter !== "all"}>
        {r.actions.length === 0 && <Typography.Text type="secondary">No actions yet; build the model on the model page first.</Typography.Text>}
        {r.actions.filter(show).map((a) => (
          <Card
            key={a.id}
            size="small"
            type="inner"
            style={{ marginBottom: 12 }}
            title={
              <Space>
                <Link to={`/suts/${sutId}/model?node=${a.id}`}>{a.name}</Link>
                {a.uncovered && <Tag color="orange">Not covered</Tag>}
              </Space>
            }
            extra={markBox("action", a.id, a.mark)}
          >
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="Purpose">{a.description || <Typography.Text type="warning">Not filled in</Typography.Text>}</Descriptions.Item>
              <Descriptions.Item label="API">
                {a.apis.length ? a.apis.map((x) => <Tag key={x.id}>{`${x.method} ${x.path}`}</Tag>) : <Typography.Text type="warning">Not bound</Typography.Text>}
              </Descriptions.Item>
              <Descriptions.Item label="Type">{a.inputs.join(", ") || "None"}</Descriptions.Item>
              <Descriptions.Item label="Outputs">{a.outputs.join(", ") || "None"}</Descriptions.Item>
              <Descriptions.Item label="Preconditions">{a.preconditions.join("; ") || "None"}</Descriptions.Item>
              <Descriptions.Item label="Effects">{a.effects.join("; ") || "None"}</Descriptions.Item>
              <Descriptions.Item label="Coverage">
                <CoverageLine coverage={a.coverage} uncovered={a.uncovered} />
              </Descriptions.Item>
            </Descriptions>
            {noteBox("action", a.id, a.mark)}
          </Card>
        ))}
        </ListSection>
      </Card>
    </Space>
  );
}
