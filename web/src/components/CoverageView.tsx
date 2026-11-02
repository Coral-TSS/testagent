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
          <Statistic title="Active cases" value={coverage.cases} />
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title={`Requirement coverage ${r.covered}/${r.total}`}>
          <Progress percent={pct(r.covered, r.total)} />
          <Typography.Text type="secondary">Uncovered requirements: </Typography.Text>
          {r.uncovered.length ? r.uncovered.map((u) => <Tag color="red" key={u.id}>{`${u.code} ${u.title || ""}`}</Tag>) : <Tag color="green">None</Tag>}
        </Card>
      </Col>
      <Col span={9}>
        <Card size="small" title={`Action node coverage ${a.covered}/${a.total}`}>
          <Progress percent={pct(a.covered, a.total)} />
          <Typography.Text type="secondary">Uncovered actions: </Typography.Text>
          {a.uncovered.length ? a.uncovered.map((u) => <Tag color="orange" key={u.id}>{u.name}</Tag>) : <Tag color="green">None</Tag>}
        </Card>
      </Col>
      {coverage.fields && coverage.fields.total > 0 && (
        <Col span={24} style={{ marginTop: 12 }}>
          <Card size="small" title={`Field coverage ${coverage.fields.covered}/${coverage.fields.total} (entity fields referenced by requirements)`}>
            <Progress percent={pct(coverage.fields.covered, coverage.fields.total)} />
            <Typography.Text type="secondary">Uncovered fields: </Typography.Text>
            {coverage.fields.uncovered.length ? (
              coverage.fields.uncovered.map((u) => (
                <Tag color="orange" key={u.id}>
                  {u.name}
                </Tag>
              ))
            ) : (
              <Tag color="green">None</Tag>
            )}
          </Card>
        </Col>
      )}
      {coverage.relations && coverage.relations.total > 0 && (
        <Col span={24} style={{ marginTop: 12 }}>
          <Card size="small" title={`Link coverage ${coverage.relations.covered}/${coverage.relations.total} (entity links referenced by requirements)`}>
            <Progress percent={pct(coverage.relations.covered, coverage.relations.total)} />
            <Typography.Text type="secondary">Uncovered links: </Typography.Text>
            {coverage.relations.uncovered.length ? (
              coverage.relations.uncovered.map((u) => (
                <Tag color="orange" key={u.id}>
                  {u.name}
                </Tag>
              ))
            ) : (
              <Tag color="green">None</Tag>
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
            <Dist title="Priority distribution" data={coverage.by_priority} />
            <Dist title="Type distribution" data={coverage.by_type} />
            <Dist title="Scenario distribution" data={coverage.by_scenario} labels={scenarioLabels} />
          </>
        ) : (
          <Empty description="No cases yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Col>
    </Row>
  );
}
