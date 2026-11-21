import { ReadingDrawer } from "./ReadingDrawer";
import { RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Divider, Form, Input, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, describeError } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AiOutcome, EntityField, Graph, Link as ModelLink, Requirement } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { PeopleRolePicker, peoplePayload } from "./PeopleRolePicker";
import { confirmDiscard } from "./panel/UnsavedGuard";
import { RequirementStatusTag } from "./StatusTags";
import { StructureEditor, cleanStructure } from "./StructureEditor";
import { RequirementCoverage } from "./CoverageDetail";
import { SuggestionList } from "./SuggestionList";
import { objLabel } from "./ObjLink";

/** P06 requirement detail: edit, owners, five-part structure (human/AI), confirm */
export function RequirementDrawer(props: {
  reqId: string | null;
  sutId: string;
  locked: boolean;
  onClose: () => void;
  onOpenRun: (runId: string) => void;
}) {
  const { reqId, sutId, locked } = props;
  const qc = useQueryClient();
  const { message, modal } = App.useApp();
  const [form] = Form.useForm();
  const [peopleForm] = Form.useForm();
  const [structureForm] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const req = useQuery({
    queryKey: ["requirement", reqId],
    queryFn: () => api<Requirement>(`/requirements/${reqId}`),
    enabled: Boolean(reqId),
  });
  const graph = useQuery({ queryKey: ["graph", sutId, null], queryFn: () => api<Graph>(`/suts/${sutId}/graph`), enabled: Boolean(reqId) });
  const links = useQuery({
    queryKey: ["links", sutId],
    queryFn: () => api<ModelLink[]>(`/suts/${sutId}/links`),
    enabled: Boolean(reqId),
  });
  const fields = useQuery({
    queryKey: ["sut-fields", sutId],
    queryFn: () => api<EntityField[]>(`/suts/${sutId}/fields`),
    enabled: Boolean(reqId),
  });
  useEffect(() => {
    if (req.data) form.setFieldsValue(req.data);
  }, [req.data, form]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["requirement", reqId] });
    qc.invalidateQueries({ queryKey: ["requirements"] });
    qc.invalidateQueries({ queryKey: ["suggestions", sutId] });
  };
  const saveAll = async () => {
    const basics = await form.validateFields();
    setSaving(true);
    try {
      await api(`/requirements/${reqId}`, { method: "PATCH", body: basics });
      await api(`/requirements/${reqId}/people`, { method: "PUT", body: peoplePayload(peopleForm.getFieldsValue()) });
      await api(`/requirements/${reqId}/structure`, { method: "PUT", body: cleanStructure(structureForm.getFieldsValue()) });
      message.success("已保存");
      refresh();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setSaving(false);
    }
  };
  const close = async () => {
    const dirty = form.isFieldsTouched() || peopleForm.isFieldsTouched() || structureForm.isFieldsTouched();
    if (dirty && !(await confirmDiscard(modal))) return;
    props.onClose();
  };
  const ai = useApiMutation(() => api<AiOutcome>(`/requirements/${reqId}/structure`, { method: "POST" }), {
    onSuccess: (out) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["agent-runs"] });
      props.onOpenRun(out.agent_run_id);
    },
  });
  const confirm = useApiMutation(() => api(`/requirements/${reqId}/confirm`, { method: "POST" }), { onSuccess: refresh, success: "需求已确认" });
  const r = req.data;
  const editable = !locked;

  return (
    <ReadingDrawer kind="requirement"
      open={Boolean(reqId)}
      onClose={() => void close()}
      footer={
        r && editable ? (
          <Space>
            <Button onClick={() => void close()}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => void saveAll()}>保存</Button>
          </Space>
        ) : null
      }
      title={
        r ? (
          <Space>
            {r.code} {r.title} <RequirementStatusTag status={r.status} />
          </Space>
        ) : (
          "需求"
        )
      }
      extra={
        r && (
          <Space>
            {r.agent_run_id && <Button onClick={() => props.onOpenRun(r.agent_run_id!)}>查看 AI 追踪</Button>}
            <Button icon={<RobotOutlined />} disabled={!editable} loading={ai.isPending} onClick={() => ai.mutate()}>
              AI 结构化
            </Button>
            <Popconfirm title="要确认该需求吗？已确认的需求是冻结的前提。" onConfirm={() => confirm.mutate()} disabled={!editable || r.status === "confirmed"}>
              <Button type="primary" disabled={!editable || r.status === "confirmed"}>
                确认
              </Button>
            </Popconfirm>
          </Space>
        )
      }
    >
      {r && (
        <>
          {locked && <Alert type="info" showIcon style={{ marginBottom: 12 }} title="该版本的需求已冻结且只读。要修改请先解冻版本（必须填写原因）。" />}
          <Form name="requirement-detail" form={form} layout="vertical" disabled={!editable}>
            <Form.Item name="title" label="标题" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="priority" label="优先级">
              <Select style={{ width: 120 }} options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
            </Form.Item>
            <Form.Item name="raw_text" label="需求正文">
              <Input.TextArea autoSize={{ minRows: 4 }} />
            </Form.Item>
          </Form>
          <Divider titlePlacement="start">负责人</Divider>
          <PeopleRolePicker form={peopleForm} showSave={false} value={r.people} disabled={!editable} onSave={() => undefined} />
          <Divider titlePlacement="start">结构（执行者 / 前置条件 / 动作 / 预期结果 / 约束）</Divider>
          <StructureEditor
            form={structureForm}
            showSave={false}
            value={r.structured}
            nodes={graph.data?.nodes || []}
            fields={fields.data || []}
            links={links.data || []}
            disabled={!editable}
            onSave={() => undefined}
          />
          {(r.fields?.length || 0) > 0 && (
            <Space wrap style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">涉及字段： </Typography.Text>
              {r.fields!.map((f) => (
                <Tag key={f.id} color="purple">
                  <Link to={`/suts/${sutId}/model?node=${f.node_id}`}>{fieldLabel(f)}</Link>
                </Tag>
              ))}
            </Space>
          )}
          {(r.links?.length || 0) > 0 && (
            <Space wrap style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">涉及关系： </Typography.Text>
              {r.links!.map((l) => (
                <Tag key={`${l.part}:${l.link_id}`} color="volcano">
                  <Link to={`/suts/${sutId}/review`}>{`${l.from_name} ${l.forward_name} ${l.to_name}`}</Link>
                </Tag>
              ))}
            </Space>
          )}
          <Divider titlePlacement="start">关联用例（{r.cases?.length || 0}）</Divider>
          {r.cases?.length ? (
            <Space wrap>
              {r.cases.map((c) => (
                <Link key={c.id} to={`/cases/${c.id}`}>
                  <Tag color={c.status === "ready" ? "green" : c.status === "deprecated" ? "default" : "blue"}>{objLabel(c.title, c.code)}</Tag>
                </Link>
              ))}
            </Space>
          ) : (
            <Typography.Text type="secondary">暂无测试用例；请在“测试用例与覆盖”页签用 AI 生成或手工创建。</Typography.Text>
          )}
          {r.coverage && (
            <>
              <Divider titlePlacement="start">覆盖详情</Divider>
              <RequirementCoverage coverage={r.coverage} sutId={sutId} />
            </>
          )}
          {(r.suggestions?.length || 0) > 0 && (
            <>
              <Divider titlePlacement="start">模型建议</Divider>
              <SuggestionList sutId={sutId} items={r.suggestions!} onChanged={refresh} />
            </>
          )}
          <Typography.Paragraph type="secondary" style={{ marginTop: 16, fontSize: 12 }}>
            AI 的输出都是草稿：结构化结果需要人工确认，模型建议需要人工采纳。
          </Typography.Paragraph>
        </>
      )}
    </ReadingDrawer>
  );
}
