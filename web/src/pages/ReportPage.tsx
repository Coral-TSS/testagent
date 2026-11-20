import { ListSection, ListTable } from "../components/ListView";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Row, Space, Statistic, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Report, ReportContent, SuspectedCause } from "../api/types";
import { CAUSE_TAG, CauseTag } from "../components/FailureSummary";
import { CAUSE_LABEL, DefectStatusTag, ROLE_LABEL, SEVERITY, SeverityTag } from "../components/DefectTags";
import { ExecutionStatusTag } from "../components/StatusTags";
import { ByRole, RequirementStatsTable, fmtScore } from "../components/StatsTables";
import { SCOPE_LABEL, passRateNote, passRateText, pct } from "./ReportsPage";
import { CorrectionButton } from "../components/CorrectionButton";

type PersonRow = ReportContent["by_person"][number];
type DefectRow = ReportContent["defects"][number];
type FailureRow = ReportContent["failures"][number];

/** P11 report detail: read-only snapshot (immutable once generated; regenerate for fresh data) */
export function ReportPage() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["report", reportId], queryFn: () => api<Report>(`/reports/${reportId}`) });
  const r = q.data;
  const regenerate = useApiMutation(
    () =>
      r!.scope_type === "version"
        ? api<Report>(`/versions/${r!.scope_id}/report`, { method: "POST" })
        : api<Report>(`/runs/${r!.scope_id}/report`, { method: "POST" }),
    { success: "已生成新报告（原报告保持不变）", invalidate: [["reports"]], onSuccess: (n) => navigate(`/reports/${n.id}`) },
  );
  if (!r) return <Card loading={q.isLoading}>{q.isError && "未找到报告"}</Card>;
  const c = r.content;
  const s = c.summary;
  const weights = Object.keys(SEVERITY)
    .filter((k) => k in c.weights_used)
    .map((k) => `${SEVERITY[k][0]} ${c.weights_used[k]}`)
    .join(" · ");
  return (
    <>
      <Card
        style={{ marginBottom: 16 }}
        title={
          <>
            {SCOPE_LABEL[r.scope_type]}: {c.scope.type === "version" ? `Version ${c.scope.version_name}` : `${c.scope.task_name} · version ${c.scope.version_name}`}
          </>
        }
        extra={
          <Space>
            <CorrectionButton targetType="report" targetId={r.id} placeholder="例如：失败被归到了错误的需求；摘要把环境问题写成了开发问题" />
            <Button loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
              重新生成
            </Button>
          </Space>
        }
      >
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="报告是生成当刻的快照，生成后不可更改；重新生成会得到一份新报告。" />
        <Row gutter={16} style={{ marginBottom: 12 }}>
          <Col span={4}><Statistic title="用例" value={s.total} /></Col>
          <Col span={4}><Statistic title="通过" value={s.passed} /></Col>
          <Col span={4}><Statistic title="失败 / 错误" value={`${s.failed} / ${s.error}`} /></Col>
          <Col span={4}><Statistic title="阻塞 / 跳过" value={`${s.blocked} / ${s.skipped}`} /></Col>
          <Col span={4}><Statistic title="未执行" value={s.not_executed} /></Col>
          <Col span={4}><Statistic title="通过率" value={passRateText(s)} /></Col>
        </Row>
        {(s.skipped > 0 || s.blocked > 0 || s.not_executed > 0) && (
          <Alert type="warning" showIcon style={{ marginBottom: 12 }} data-testid="pass-rate-note" title={passRateNote(s)} />
        )}
        {s.by_cause && Object.values(s.by_cause).some((n) => n > 0) && (
          <Space wrap style={{ marginBottom: 12 }} data-testid="by-cause">
            <Typography.Text type="secondary">按可疑原因分类的失败：</Typography.Text>
            {(Object.entries(s.by_cause) as [SuspectedCause, number][])
              .filter(([, n]) => n > 0)
              .map(([cause, n]) => (
                <Tag key={cause} color={CAUSE_TAG[cause][1]}>
                  {CAUSE_TAG[cause][0]} {n}
                </Tag>
              ))}
            {(s.by_cause.platform || 0) + (s.by_cause.environment || 0) > 0 && (
              <Typography.Text type="secondary">平台和环境失败不是被测系统的缺陷。</Typography.Text>
            )}
          </Space>
        )}
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="生成于">{dayjs(r.created_at).format("YYYY-MM-DD HH:mm:ss")}</Descriptions.Item>
          <Descriptions.Item label="生成者">{r.created_by === "system" ? "系统（执行结束时自动生成）" : r.created_by}</Descriptions.Item>
          <Descriptions.Item label="严重级别权重">{weights}</Descriptions.Item>
          {c.scope.task_run_id && (
            <Descriptions.Item label="执行">
              <Link to={`/runs/${c.scope.task_run_id}`}>查看执行</Link>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="版本">
            <Link to={`/versions/${c.scope.version_id}`}>{c.scope.version_name}</Link>
          </Descriptions.Item>
          <Descriptions.Item label="模型快照">{c.snapshot_id ? <Tag color="purple">已关联</Tag> : "-"}</Descriptions.Item>
        </Descriptions>
      </Card>

      {(c.by_category?.length ?? 0) > 0 && (
        <Card style={{ marginBottom: 16 }} title="按用例类别：通过率 = 通过 ÷ 已执行（跳过、阻塞和未执行不计入）" data-testid="by-category">
          <ListTable
            pagination={false}
            label="类别结果"
            size="small"
            rowKey="category"

            dataSource={c.by_category}
            columns={[
              { title: "类别", dataIndex: "label" },
              { title: "用例", dataIndex: "total" },
              { title: "已执行", render: (_: unknown, r: NonNullable<ReportContent["by_category"]>[number]) => r.executed ?? r.passed + r.failed + r.error },
              { title: "通过", dataIndex: "passed" },
              { title: "失败 / 错误", render: (_: unknown, r: NonNullable<ReportContent["by_category"]>[number]) => `${r.failed} / ${r.error}` },
              { title: "跳过 / 阻塞 / 未执行", render: (_: unknown, r: NonNullable<ReportContent["by_category"]>[number]) => `${r.skipped} / ${r.blocked} / ${r.not_executed}` },
              { title: "通过率", dataIndex: "pass_rate", render: (v: number | null) => pct(v) },
            ]}
          />
        </Card>
      )}
      <Card style={{ marginBottom: 16 }} title="AI 摘要">
        {r.ai_summary ? (
          <>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{r.ai_summary}</Typography.Paragraph>
            {r.agent_run_id && <Link to={`/agent/runs?run=${r.agent_run_id}`}>查看 Agent 追踪</Link>}
          </>
        ) : (
          <Typography.Text type="secondary">没有 AI 摘要（未配置模型或生成失败）；不影响下方统计。</Typography.Text>
        )}
      </Card>

      <Card style={{ marginBottom: 16 }} title="按需求：缺陷密度（缺陷数 ÷ 已执行用例）和严重级别加权分">
        <RequirementStatsTable rows={c.by_requirement} paginate={false} />
      </Card>

      <Card style={{ marginBottom: 16 }} title="按人员：已归因缺陷（已拒绝的缺陷不计入）">
        <ListTable<PersonRow>
          pagination={false}
          label="报告人员"
          size="small"
          rowKey="person_id"

          dataSource={c.by_person}
          locale={{ emptyText: "暂无人员数据" }}
          columns={[
            { title: "人员", dataIndex: "name", render: (v: string, p) => <Link to={`/defects?person_id=${p.person_id}`}>{v}</Link> },
            { title: "已归因缺陷", dataIndex: "attributed_count", width: 90 },
            { title: "加权分", dataIndex: "attributed_score", width: 80, render: fmtScore },
            { title: "按角色", dataIndex: "attributed_by_role", render: (v: PersonRow["attributed_by_role"]) => <ByRole value={v} /> },
            { title: "相关缺陷", dataIndex: "related_count", width: 90 },
            { title: "主要需求", dataIndex: "top_requirements", render: (v: string[]) => v.map((x) => <Tag key={x}>{x}</Tag>) },
          ]}
        />
      </Card>

      <Card style={{ marginBottom: 16 }} title={`失败与错误（${c.failures.length}）`}>
        <ListTable<FailureRow>
          pagination={false}
          label="失败的执行"
          size="small"
          rowKey="execution_id"
          dataSource={c.failures}
          locale={{ emptyText: "没有失败的用例" }}
          columns={[
            { title: "用例", dataIndex: "case", render: (v: FailureRow["case"]) => <Link to={`/cases/${v.id}`}>{v.code} {v.title}</Link> },
            { title: "需求", dataIndex: "requirement_codes", render: (v: string[]) => v.map((x) => <Tag key={x}>{x}</Tag>) },
            { title: "结果", dataIndex: "status", width: 80, render: (v: string) => <ExecutionStatusTag status={v} /> },
            { title: "原因", key: "cause", width: 150, render: (_: unknown, f) => <CauseTag cause={f.suspected_cause} /> },
            { title: "失败的断言 / 错误", key: "why", render: (_: unknown, f) => f.headline || f.failed_assertion || f.error || "-" },
            { title: "执行", dataIndex: "execution_id", width: 70, render: (v: string) => <Link to={`/executions/${v}`}>详情</Link> },
            { title: "缺陷", dataIndex: "defect_ids", width: 70, render: (v: string[]) => v.length || "-" },
          ]}
        />
      </Card>

      {(c.no_script?.length || 0) > 0 && (
        <Card style={{ marginBottom: 16 }} title={`未执行：无自动化脚本（${c.no_script!.length}）`} data-testid="report-no-script">
          <Typography.Paragraph type="secondary">这些用例在自动化任务中但还没有脚本；已被跳过，不计入通过率。</Typography.Paragraph>
          <ListSection label="报告无脚本的用例" count={c.no_script!.length}>
          <Space wrap>
            {c.no_script!.map((n) => (
              <Link key={n.execution_id} to={`/cases/${n.case.id}`}>
                {n.case.code} {n.case.title}
              </Link>
            ))}
          </Space>
          </ListSection>
        </Card>
      )}

      <Card style={{ marginBottom: 16 }} title={`缺陷（${c.defects.length}）`}>
        <ListTable<DefectRow>
          pagination={false}
          label="报告缺陷"
          size="small"
          rowKey="id"
          dataSource={c.defects}
          locale={{ emptyText: "暂无缺陷" }}
          columns={[
            { title: "编号", dataIndex: "code", width: 90, render: (v: string, d) => <Link to={`/defects/${d.id}`}>{v}</Link> },
            { title: "标题", dataIndex: "title" },
            { title: "严重级别", dataIndex: "severity", width: 80, render: (v: string) => <SeverityTag value={v} /> },
            { title: "状态（生成时）", dataIndex: "status", width: 110, render: (v: string) => <DefectStatusTag status={v} /> },
            { title: "原因", dataIndex: "cause_category", width: 100, render: (v: string) => CAUSE_LABEL[v] || v },
            { title: "需求", dataIndex: "requirements", render: (v: string[]) => v.map((x) => <Tag key={x}>{x}</Tag>) },
            {
              title: "归因于",
              dataIndex: "responsible",
              render: (v: DefectRow["responsible"]) => v.map((p) => `${p.name} (${ROLE_LABEL[p.role] || p.role})`).join(", ") || "-",
            },
          ]}
        />
      </Card>

      <Card title="代码关联（需求 → 节点 / API → 代码位置）">
        <ListSection label="报告代码关联" count={c.code_links.filter((l) => l.nodes.length || l.apis.length).length}>
        {c.code_links.every((l) => !l.nodes.length && !l.apis.length) ? (
          <Typography.Text type="secondary">没有关联的节点或 API</Typography.Text>
        ) : (
          c.code_links
            .filter((l) => l.nodes.length || l.apis.length)
            .map((l) => (
              <Descriptions key={l.requirement_code} size="small" column={1} title={l.requirement_code} style={{ marginBottom: 8 }}>
                {l.nodes.map((n) => (
                  <Descriptions.Item key={`n-${n.name}`} label="节点">
                    {n.name}
                    {n.code_ref ? ` · ${n.code_ref}` : ""}
                  </Descriptions.Item>
                ))}
                {l.apis.map((a) => (
                  <Descriptions.Item key={`a-${a.method}-${a.path}`} label="API">
                    {`${a.method} ${a.path}`}
                    {a.code_ref ? ` · ${a.code_ref}` : ""}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            ))
        )}
        </ListSection>
      </Card>
    </>
  );
}
