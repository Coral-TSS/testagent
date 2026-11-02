import { useQuery } from "@tanstack/react-query";
import { Col, Form, Input, Row, Select, type FormInstance } from "antd";

import { api } from "../api/client";
import type { Graph, Requirement, TestCase } from "../api/types";
import { SCENARIO } from "./CaseTags";
import { KIND_LABEL } from "./StatusTags";
import { StepsEditor } from "./StepsEditor";
import { categoryOptions, qualityTagOptions } from "../utils/categories";

export interface CaseFormValues {
  title: string;
  test_point?: string;
  priority?: string;
  type_tag?: string;
  scenario?: string;
  category?: string;
  quality_tags?: string[];
  mode?: string;
  preconditions?: string;
  steps?: { action: string; data?: string; expected?: string }[];
  test_data?: string;
  expected?: string;
  code_path?: string;
  requirement_ids?: string[];
  node_ids?: string[];
}

export function caseToForm(c: TestCase): CaseFormValues {
  return {
    title: c.title,
    test_point: c.test_point || undefined,
    priority: c.priority,
    type_tag: c.type_tag,
    scenario: c.scenario || undefined,
    category: c.category || "requirement",
    quality_tags: c.quality_tags || [],
    mode: c.mode,
    preconditions: c.preconditions || undefined,
    steps: c.steps.map((s) => ({ action: s.action, data: s.data || undefined, expected: s.expected || undefined })),
    test_data: c.test_data ? JSON.stringify(c.test_data, null, 2) : "",
    expected: c.expected || undefined,
    code_path: c.code_path || undefined,
    requirement_ids: c.requirements.map((r) => r.id),
    node_ids: c.nodes.map((n) => n.id),
  };
}

/** Converts form values to the API body; returns an error message for invalid test data JSON. */
export function formToBody(v: CaseFormValues): { body?: Record<string, unknown>; error?: string } {
  let testData: unknown = null;
  const raw = (v.test_data || "").trim();
  if (raw) {
    try {
      testData = JSON.parse(raw);
    } catch {
      return { error: "Test data is not valid JSON" };
    }
    if (typeof testData !== "object" || Array.isArray(testData) || testData === null) {
      return { error: "Test data must be a JSON object, e.g. {\"amount\": 0}" };
    }
  }
  const blank = (s?: string) => (s && s.trim() ? s.trim() : null);
  return {
    body: {
      title: v.title,
      test_point: blank(v.test_point),
      priority: v.priority || "P1",
      type_tag: v.type_tag || "functional",
      scenario: v.scenario || null,
      category: v.category || "requirement",
      quality_tags: v.quality_tags || [],
      mode: v.mode || "manual",
      preconditions: blank(v.preconditions),
      steps: (v.steps || []).filter((s) => s?.action?.trim()),
      test_data: testData,
      expected: blank(v.expected),
      code_path: blank(v.code_path),
      requirement_ids: v.requirement_ids || [],
      node_ids: v.node_ids || [],
    },
  };
}

/** Case fields; requirement choices come from the given version, nodes from the SUT model. */
export function CaseForm({
  form,
  sutId,
  versionId,
  disabled,
  onFinish,
}: {
  form: FormInstance<CaseFormValues>;
  sutId: string;
  versionId?: string | null;
  disabled?: boolean;
  onFinish: (v: CaseFormValues) => void;
}) {
  const reqs = useQuery({
    queryKey: ["requirements", versionId],
    queryFn: () => api<Requirement[]>(`/versions/${versionId}/requirements`),
    enabled: Boolean(versionId),
  });
  const graph = useQuery({ queryKey: ["graph", sutId, null], queryFn: () => api<Graph>(`/suts/${sutId}/graph`), enabled: Boolean(sutId) });
  return (
    <Form form={form} layout="vertical" disabled={disabled} onFinish={onFinish} initialValues={{ priority: "P1", type_tag: "functional", category: "requirement", quality_tags: [], mode: "manual", steps: [] }}>
      <Row gutter={12}>
        <Col span={16}>
          <Form.Item name="title" label="Title" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="scenario" label="Scenario">
            <Select allowClear options={Object.entries(SCENARIO).map(([value, [label]]) => ({ value, label }))} />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item name="test_point" label="Test point">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="priority" label="Priority">
            <Select options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="type_tag" label="Type" rules={[{ pattern: /^[a-z][a-z0-9_-]{0,31}$/, message: "starts with a lowercase letter" }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="category" label="category" tooltip="Requirement validation: the business rules in the requirement (incl. input validation/error codes); General quality: idempotency, concurrency, repeatability/data reset; Regression smoke: guards the main path">
            <Select options={categoryOptions} />
          </Form.Item>
        </Col>
        <Col span={16}>
          <Form.Item noStyle shouldUpdate={(a, b) => a.category !== b.category}>
            {({ getFieldValue }) =>
              getFieldValue("category") === "quality" ? (
                <Form.Item name="quality_tags" label="Quality attributes">
                  <Select mode="tags" options={qualityTagOptions} />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="mode" label="Mode">
            <Select options={[{ value: "manual", label: "Manual" }, { value: "automated", label: "Automated" }]} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="requirement_ids" label="Requirements">
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={(reqs.data || []).map((r) => ({ value: r.id, label: `${r.code} ${r.title}` }))}
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="node_ids" label="Linked model nodes">
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={(graph.data?.nodes || []).map((n) => ({ value: n.id, label: `${KIND_LABEL[n.kind]} · ${n.name}` }))}
            />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item name="preconditions" label="Preconditions">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="Steps">
            <StepsEditor disabled={disabled} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="test_data" label="Test data (JSON object)">
            <Input.TextArea rows={4} style={{ fontFamily: "monospace" }} placeholder='{"amount": 0}' />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="expected" label="Expected result">
            <Input.TextArea rows={4} />
          </Form.Item>
        </Col>
        <Col span={24}>
          <Form.Item name="code_path" label="Automation code path (optional)">
            <Input placeholder="tests/REQ-001/test_TC-001.py" />
          </Form.Item>
        </Col>
      </Row>
    </Form>
  );
}
