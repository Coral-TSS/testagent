import { RobotOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Divider, Drawer, Form, Input, Popconfirm, Select, Space, Tag, Typography } from "antd";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { AiOutcome, EntityField, Graph, Link as ModelLink, Requirement } from "../api/types";
import { fieldLabel } from "./EntityFields";
import { PeopleRolePicker } from "./PeopleRolePicker";
import { RequirementStatusTag } from "./StatusTags";
import { StructureEditor } from "./StructureEditor";
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
  const [form] = Form.useForm();
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
  const opts = { onSuccess: refresh };
  const update = useApiMutation((body: Record<string, unknown>) => api(`/requirements/${reqId}`, { method: "PATCH", body }), { ...opts, success: "Saved" });
  const people = useApiMutation((body: unknown) => api(`/requirements/${reqId}/people`, { method: "PUT", body }), { ...opts, success: "People saved" });
  const structure = useApiMutation((body: unknown) => api(`/requirements/${reqId}/structure`, { method: "PUT", body }), { ...opts, success: "Structure saved" });
  const ai = useApiMutation(() => api<AiOutcome>(`/requirements/${reqId}/structure`, { method: "POST" }), {
    onSuccess: (out) => {
      refresh();
      qc.invalidateQueries({ queryKey: ["agent-runs"] });
      props.onOpenRun(out.agent_run_id);
    },
  });
  const confirm = useApiMutation(() => api(`/requirements/${reqId}/confirm`, { method: "POST" }), { ...opts, success: "Requirement confirmed" });
  const r = req.data;
  const editable = !locked;

  return (
    <Drawer
      open={Boolean(reqId)}
      onClose={props.onClose}
      size={720}
      title={
        r ? (
          <Space>
            {r.code} {r.title} <RequirementStatusTag status={r.status} />
          </Space>
        ) : (
          "Requirement"
        )
      }
      extra={
        r && (
          <Space>
            {r.agent_run_id && <Button onClick={() => props.onOpenRun(r.agent_run_id!)}>View AI trace</Button>}
            <Button icon={<RobotOutlined />} disabled={!editable} loading={ai.isPending} onClick={() => ai.mutate()}>
              AI structure
            </Button>
            <Popconfirm title="Confirm this requirement? Confirmed requirements are a prerequisite for freezing." onConfirm={() => confirm.mutate()} disabled={!editable || r.status === "confirmed"}>
              <Button type="primary" disabled={!editable || r.status === "confirmed"}>
                Confirm
              </Button>
            </Popconfirm>
          </Space>
        )
      }
    >
      {r && (
        <>
          {locked && <Alert type="info" showIcon style={{ marginBottom: 12 }} title="The version's requirements are frozen and read-only. To change them, unfreeze the version first (a reason is required)." />}
          <Form form={form} layout="vertical" disabled={!editable} onFinish={(v) => update.mutate(v)}>
            <Form.Item name="title" label="Title" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="priority" label="Priority">
              <Select style={{ width: 120 }} options={["P0", "P1", "P2"].map((p) => ({ value: p, label: p }))} />
            </Form.Item>
            <Form.Item name="raw_text" label="Requirement text">
              <Input.TextArea rows={4} />
            </Form.Item>
            {editable && (
              <Button size="small" htmlType="submit" loading={update.isPending}>
                Save basic info
              </Button>
            )}
          </Form>
          <Divider titlePlacement="start">Owners</Divider>
          <PeopleRolePicker value={r.people} disabled={!editable} saving={people.isPending} onSave={(p) => people.mutate(p)} />
          <Divider titlePlacement="start">Structure (actor / preconditions / action / expected result / constraints)</Divider>
          <StructureEditor
            value={r.structured}
            nodes={graph.data?.nodes || []}
            fields={fields.data || []}
            links={links.data || []}
            disabled={!editable}
            saving={structure.isPending}
            onSave={(s) => structure.mutate(s)}
          />
          {(r.fields?.length || 0) > 0 && (
            <Space wrap style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">Fields involved: </Typography.Text>
              {r.fields!.map((f) => (
                <Tag key={f.id} color="purple">
                  <Link to={`/suts/${sutId}/model?node=${f.node_id}`}>{fieldLabel(f)}</Link>
                </Tag>
              ))}
            </Space>
          )}
          {(r.links?.length || 0) > 0 && (
            <Space wrap style={{ marginTop: 8 }}>
              <Typography.Text type="secondary">Links involved: </Typography.Text>
              {r.links!.map((l) => (
                <Tag key={`${l.part}:${l.link_id}`} color="volcano">
                  <Link to={`/suts/${sutId}/review`}>{`${l.from_name} ${l.forward_name} ${l.to_name}`}</Link>
                </Tag>
              ))}
            </Space>
          )}
          <Divider titlePlacement="start">Linked cases ({r.cases?.length || 0})</Divider>
          {r.cases?.length ? (
            <Space wrap>
              {r.cases.map((c) => (
                <Link key={c.id} to={`/cases/${c.id}`}>
                  <Tag color={c.status === "ready" ? "green" : c.status === "deprecated" ? "default" : "blue"}>{objLabel(c.title, c.code)}</Tag>
                </Link>
              ))}
            </Space>
          ) : (
            <Typography.Text type="secondary">No cases yet; generate them by AI or create them by hand in the “Test cases & coverage” tab.</Typography.Text>
          )}
          {r.coverage && (
            <>
              <Divider titlePlacement="start">Coverage detail</Divider>
              <RequirementCoverage coverage={r.coverage} sutId={sutId} />
            </>
          )}
          {(r.suggestions?.length || 0) > 0 && (
            <>
              <Divider titlePlacement="start">Model suggestions</Divider>
              <SuggestionList sutId={sutId} items={r.suggestions!} onChanged={refresh} />
            </>
          )}
          <Typography.Paragraph type="secondary" style={{ marginTop: 16, fontSize: 12 }}>
            All AI output is a draft: structuring results need human confirmation, model suggestions need human acceptance.
          </Typography.Paragraph>
        </>
      )}
    </Drawer>
  );
}
