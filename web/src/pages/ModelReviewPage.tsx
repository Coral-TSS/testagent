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

/** Who touches an element: requirements and cases, each as "标题（编号）" links; uncovered highlighted. */
export function CoverageLine({ coverage, uncovered }: { coverage: ReviewCoverage; uncovered: boolean }) {
  if (uncovered) return <Tag color="orange">未覆盖：没有需求或用例关联到它</Tag>;
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

/** Read-only review page of a SUT's model with per-element "已评审" marks. */
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
      <Checkbox checked={Boolean(m?.reviewed)} onChange={(e) => mark(type, id, e.target.checked, m?.note)} aria-label="已评审">
        已评审
      </Checkbox>
      {m?.stale && <Tag color="red">评审后又有变更，请重新评审</Tag>}
    </Space>
  );
  const noteBox = (type: Target, id: string, m?: ReviewMark | null) =>
    m?.reviewed ? (
      <Input
        size="small"
        placeholder="评审备注（可选，离开输入框时保存）"
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
              导出 Markdown
            </Button>
            <Button icon={<PrinterOutlined />} onClick={() => window.print()}>
              打印
            </Button>
            <Link to={`/suts/${sutId}/model`}>在模型页编辑</Link>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          title="评审清单"
          description={
            <ol style={{ margin: 0, paddingInlineStart: 20 }}>
              <li>实体：字段名与 API/代码字段一致；类型、必填标记和枚举值正确；没有遗漏业务对象。</li>
              <li>关系：两个方向读起来自然（例如 PurchaseOrder belongs to Supplier / Supplier supplies PurchaseOrder）；基数和外键正确。</li>
              <li>动作：用途清楚；输入/输出、绑定的 API、前置条件与效果与真实系统一致。</li>
              <li>覆盖：标记为“未覆盖”的要素还没有需求或用例；请检查是否漏测。</li>
              <li>“已评审”只是评审辅助，并不会接受任何 AI 建议；建议仍需在版本页的“模型建议”或模型页的“关系”中逐条接受。</li>
            </ol>
          }
        />
        <Space size={32} wrap>
          <Statistic title="实体 / 字段" value={`${s.entities} / ${s.fields}`} />
          <Statistic title="关系" value={s.links} />
          <Statistic title="动作" value={s.actions} />
          <div>
            <Typography.Text type="secondary">已评审</Typography.Text>
            <Progress percent={s.total ? Math.round((s.reviewed / s.total) * 100) : 0} format={() => `${s.reviewed}/${s.total}`} style={{ width: 180 }} />
          </div>
          <Statistic title="评审后已变更" value={s.stale} styles={{ content: { color: s.stale ? "#cf1322" : undefined } }} />
          <Statistic title="未覆盖" value={s.uncovered} styles={{ content: { color: s.uncovered ? "#d46b08" : undefined } }} />
          <Statistic
            title="待处理的模型建议"
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
              { value: "all", label: "全部" },
              { value: "todo", label: "未评审" },
              { value: "uncovered", label: "未覆盖" },
            ]}
          />
        </div>
      </Card>

      <Card title={`Entities (${r.entities.length})`}>
        <ListSection label="评审实体" count={r.entities.filter(show).length} total={r.entities.length} filtered={filter !== "all"}>
        {r.entities.length === 0 && <Typography.Text type="secondary">还没有实体；请先在模型页构建模型。</Typography.Text>}
        {r.entities.filter(show).map((e) => (
          <Card
            key={e.id}
            size="small"
            type="inner"
            style={{ marginBottom: 12 }}
            title={
              <Space>
                <Link to={`/suts/${sutId}/model?node=${e.id}`}>{e.name}</Link>
                {e.uncovered && <Tag color="orange">未覆盖</Tag>}
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
              locale={{ emptyText: "尚未登记字段" }}
              rowClassName={(f) => (f.uncovered ? "review-uncovered" : "")}
              columns={[
                { title: "字段（API 名称）", dataIndex: "name", render: (v: string) => <code>{v}</code> },
                { title: "显示名", dataIndex: "display_name", render: (v) => v || "-" },
                { title: "类型", render: (_, f) => typeText(f) },
                { title: "必填", dataIndex: "required", width: 60, render: (v: boolean) => (v ? "yes" : "no") },
                { title: "数据库列名", dataIndex: "storage_name", render: (v) => v || "-" },
                { title: "description", dataIndex: "description", ellipsis: true },
                { title: "覆盖", render: (_, f) => <CoverageLine coverage={f.coverage} uncovered={f.uncovered} /> },
              ]}
            />
            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
              <Descriptions.Item label="关系">
                {e.relations.length ? (
                  <Space orientation="vertical" size={0}>
                    {e.relations.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </Space>
                ) : (
                  "无"
                )}
              </Descriptions.Item>
              <Descriptions.Item label="覆盖">
                <CoverageLine coverage={e.coverage} uncovered={e.uncovered} />
              </Descriptions.Item>
            </Descriptions>
            {noteBox("entity", e.id, e.mark)}
          </Card>
        ))}
        </ListSection>
      </Card>

      <Card title={`Links (${r.links.length})`}>
        <ListSection label="评审关系" count={r.links.filter(show).length} total={r.links.length} filtered={filter !== "all"}>
        <List
          size="small"
          dataSource={r.links.filter(show)}
          locale={{ emptyText: "没有关系；请在模型页使用“新建关系”，或接受由外键字段生成的关系建议" }}
          renderItem={(l) => (
            <List.Item actions={[markBox("link", l.id, l.mark)]}>
              <Space orientation="vertical" size={2}>
                <span>
                  <b>{l.forward}</b> / <b>{l.reverse}</b> <Tag color="purple">{l.cardinality}</Tag>
                  {l.fk_field && <Typography.Text type="secondary">foreign key {l.fk_field}</Typography.Text>}
                  {l.via_name && <Typography.Text type="secondary"> junction entity {l.via_name}</Typography.Text>}
                  {l.required && <Tag>必填</Tag>}
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
        <ListSection label="评审动作" count={r.actions.filter(show).length} total={r.actions.length} filtered={filter !== "all"}>
        {r.actions.length === 0 && <Typography.Text type="secondary">还没有动作；请先在模型页构建模型。</Typography.Text>}
        {r.actions.filter(show).map((a) => (
          <Card
            key={a.id}
            size="small"
            type="inner"
            style={{ marginBottom: 12 }}
            title={
              <Space>
                <Link to={`/suts/${sutId}/model?node=${a.id}`}>{a.name}</Link>
                {a.uncovered && <Tag color="orange">未覆盖</Tag>}
              </Space>
            }
            extra={markBox("action", a.id, a.mark)}
          >
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="用途">{a.description || <Typography.Text type="warning">未填写</Typography.Text>}</Descriptions.Item>
              <Descriptions.Item label="API">
                {a.apis.length ? a.apis.map((x) => <Tag key={x.id}>{`${x.method} ${x.path}`}</Tag>) : <Typography.Text type="warning">未绑定</Typography.Text>}
              </Descriptions.Item>
              <Descriptions.Item label="类型">{a.inputs.join(", ") || "无"}</Descriptions.Item>
              <Descriptions.Item label="输出">{a.outputs.join(", ") || "无"}</Descriptions.Item>
              <Descriptions.Item label="前置条件">{a.preconditions.join("; ") || "无"}</Descriptions.Item>
              <Descriptions.Item label="效果">{a.effects.join("; ") || "无"}</Descriptions.Item>
              <Descriptions.Item label="覆盖">
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
