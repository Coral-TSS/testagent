import { Card, Col, Empty, Progress, Row, Statistic, Tag, Typography } from "antd";

import type { Coverage } from "../api/types";
import { SCENARIO } from "./CaseTags";
import { CoverageDetail } from "./CoverageDetail";

function pct(covered: number, total: number) {
  return total ? Math.round((covered / total) * 100) : 0;
}

function Dist({ title, data, labels }: { title: string; data: Record<string, number>; labels?: Record<string, string> }) {
  const entries = Object.entries(data);
  return (
    <div style={{ marginBottom: 8 }}>
      <Typography.Text type="secondary">{title}: </Typography.Text>
      {entries.length ? entries.map(([k, v]) => <Tag key={k}>{`${labels?.[k] || k} ${v}`}</Tag>) : "-"}
    </div>
  );
}

/** Coverage report: requirement coverage, action node coverage, priority/type/scenario distribution, uncovered lists, with per-item detail */
export function CoverageView({ coverage }: { coverage: Coverage }) {
  const { requirements: r, actions: a } = coverage;
  const scenarioLabels = Object.fromEntries(Object.entries(SCENARIO).map(([k, [l]]) => [k, l]));
  return (
    <Row gutter={16} data-testid="coverage">
      <Col span={6}>
        <Card size="small">
          <Statistic title="有效用例" value={coverage.cases} />
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title={`需求覆盖 ${r.covered}/${r.total}`}>
          <Progress percent={pct(r.covered, r.total)} />
          <Typography.Text type="secondary">未覆盖的需求： </Typography.Text>
          {r.uncovered.length ? r.uncovered.map((u) => <Tag color="red" key={u.id}>{`${u.code} ${u.title || ""}`}</Tag>) : <Tag color="green">无</Tag>}
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title={`动作节点覆盖 ${a.covered}/${a.total}`}>
          <Progress percent={pct(a.covered, a.total)} />
          <Typography.Text type="secondary">未覆盖的动作： </Typography.Text>
          {a.uncovered.length ? a.uncovered.map((u) => <Tag color="orange" key={u.id}>{u.name}</Tag>) : <Tag color="green">无</Tag>}
        </Card>
      </Col>
      {coverage.fields && coverage.fields.total > 0 && (
        <Col span={24} style={{ marginTop: 12 }}>
          <Card size="small" title={`字段覆盖 ${coverage.fields.covered}/${coverage.fields.total}（需求引用的实体字段）`}>
            <Progress percent={pct(coverage.fields.covered, coverage.fields.total)} />
            <Typography.Text type="secondary">未覆盖的字段： </Typography.Text>
            {coverage.fields.uncovered.length ? (
              coverage.fields.uncovered.map((u) => (
                <Tag color="orange" key={u.id}>
                  {u.name}
                </Tag>
              ))
            ) : (
              <Tag color="green">无</Tag>
            )}
          </Card>
        </Col>
      )}
      {coverage.relations && coverage.relations.total > 0 && (
        <Col span={24} style={{ marginTop: 12 }}>
          <Card size="small" title={`关系覆盖 ${coverage.relations.covered}/${coverage.relations.total}（需求引用的实体关系）`}>
            <Progress percent={pct(coverage.relations.covered, coverage.relations.total)} />
            <Typography.Text type="secondary">未覆盖的关系： </Typography.Text>
            {coverage.relations.uncovered.length ? (
              coverage.relations.uncovered.map((u) => (
                <Tag color="orange" key={u.id}>
                  {u.name}
                </Tag>
              ))
            ) : (
              <Tag color="green">无</Tag>
            )}
          </Card>
        </Col>
      )}
      <Col span={24} style={{ marginTop: 12 }}>
        <CoverageDetail coverage={coverage} />
      </Col>
      <Col span={24} style={{ marginTop: 12 }}>
        {coverage.cases ? (
          <>
            <Dist title="优先级分布" data={coverage.by_priority} />
            <Dist title="类型分布" data={coverage.by_type} />
            <Dist title="场景分布" data={coverage.by_scenario} labels={scenarioLabels} />
          </>
        ) : (
          <Empty description="暂无测试用例" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Col>
    </Row>
  );
}
