import { useQuery } from "@tanstack/react-query";
import { Card, Col, Descriptions, Form, Input, Row, Tag } from "antd";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Environment, Module, Sut, SutProgress, Version } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PathText } from "../components/ObjLink";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { SutExplainer } from "../components/SutExplainer";
import { EnvironmentStatus } from "../components/EnvironmentStatus";
import { SimpleCrud } from "../components/SimpleCrud";
import { VersionStatusTag } from "../components/StatusTags";

/** SUT overview: environments, optional groups, version list */
export function SutOverviewPage() {
  const { sutId = "" } = useParams();
  const sut = useQuery({ queryKey: ["sut", sutId], queryFn: () => api<Sut>(`/suts/${sutId}`) });
  const envs = useQuery({ queryKey: ["envs", sutId], queryFn: () => api<Environment[]>(`/suts/${sutId}/environments`) });
  const modules = useQuery({ queryKey: ["modules", sutId], queryFn: () => api<Module[]>(`/suts/${sutId}/modules`) });
  const versions = useQuery({ queryKey: ["versions", sutId], queryFn: () => api<Version[]>(`/suts/${sutId}/versions`) });
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const versionId = search.get("version_id") || undefined;
  const progress = useQuery({
    queryKey: ["progress", sutId, versionId || null],
    queryFn: () => api<SutProgress>(`/suts/${sutId}/progress`, { params: { version_id: versionId } }),
  });

  const createEnv = useApiMutation(
    (body: Record<string, unknown>) => api(`/suts/${sutId}/environments`, { method: "POST", body }),
    { invalidate: [["envs", sutId]], success: "Saved" },
  );
  const updateEnv = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/environments/${id}`, { method: "PATCH", body }),
    { invalidate: [["envs", sutId]], success: "Saved" },
  );
  const deleteEnv = useApiMutation((id: string) => api(`/environments/${id}`, { method: "DELETE" }), {
    invalidate: [["envs", sutId]],
  });
  const createModule = useApiMutation(
    (body: Record<string, unknown>) => api(`/suts/${sutId}/modules`, { method: "POST", body }),
    { invalidate: [["modules", sutId]], success: "Saved" },
  );
  const updateModule = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/modules/${id}`, { method: "PATCH", body }),
    { invalidate: [["modules", sutId]], success: "Saved" },
  );
  const deleteModule = useApiMutation((id: string) => api(`/modules/${id}`, { method: "DELETE" }), {
    invalidate: [["modules", sutId]],
  });

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <SutExplainer repoPath={progress.data?.repo_path} closable />
      </Col>
      <Col span={24}>
        <Card title={sut.data?.name || "SUT"} loading={sut.isLoading}>
          <Descriptions column={3}>
            <Descriptions.Item label="Code">{sut.data?.code}</Descriptions.Item>
            <Descriptions.Item label="description">{sut.data?.description || "-"}</Descriptions.Item>
            <Descriptions.Item label="Shortcuts">
              <Link to={`/suts/${sutId}/model`}>Model</Link>&nbsp;·&nbsp;<Link to={`/suts/${sutId}/review`}>Model review</Link>&nbsp;·&nbsp;
              <Link to={`/suts/${sutId}/apis`}>API registry</Link>
            </Descriptions.Item>
            <Descriptions.Item label="Local test repo (the git repository holding the automation scripts)" span={3}>
              <PathText path={progress.data?.repo_path} />
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Col span={24}>
        <Card
          title={`Getting started${progress.data?.version ? ` (version ${progress.data.version.name})` : ""}`}
          loading={progress.isLoading}
          extra={progress.data?.next ? `Next: ${progress.data.next.label}` : progress.data ? "Main flow complete" : null}
        >
          {progress.data && <OnboardingChecklist progress={progress.data} />}
        </Card>
      </Col>
      <Col span={12}>
        <Card>
          <SimpleCrud<Environment>
            title="Environment"
            emptyTitle="No environment yet"
            emptyHint="An environment is the SUT's address (e.g. http://127.0.0.1:8766). The platform checks it is reachable before running cases; with a start command it can be started in one click."
            rows={envs.data}
            loading={envs.isLoading}
            columns={[
              { title: "Name", dataIndex: "name" },
              { title: "URL", dataIndex: "base_url" },
              { title: "Status", width: 150, render: (_: unknown, e: Environment) => <EnvironmentStatus env={e} compact /> },
            ]}
            fields={
              <>
                <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="base_url" label="URL" rules={[{ required: true, pattern: /^https?:\/\/\S+$/, message: "Starts with http:// or https://" }]}>
                  <Input placeholder="http://127.0.0.1:8766" />
                </Form.Item>
                <Form.Item name="credential_ref" label="Login credential reference (optional)">
                  <Input />
                </Form.Item>
                <Form.Item
                  name="start_command"
                  label="Start command (optional, starts the SUT on this machine; run automatically on platform start when unreachable)"
                >
                  <Input placeholder="uv run uvicorn examples.procurement.api:create_app --factory --host 127.0.0.1 --port 8766" />
                </Form.Item>
              </>
            }
            onCreate={(v) => createEnv.mutateAsync(v)}
            onUpdate={(row, v) => updateEnv.mutateAsync({ id: row.id, body: v })}
            onDelete={(row) => deleteEnv.mutate(row.id)}
          />
        </Card>
      </Col>
      <Col span={12}>
        <Card>
          <SimpleCrud<Module>
            title="Groups (optional, to organise nodes by business area)"
            emptyTitle="Groups are optional"
            emptyHint="Groups are only used to filter nodes by business area on the model graph; you can skip them."
            rows={modules.data}
            loading={modules.isLoading}
            columns={[
              { title: "Name", dataIndex: "name" },
              { title: "description", dataIndex: "description" },
            ]}
            fields={
              <>
                <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="description" label="description">
                  <Input />
                </Form.Item>
              </>
            }
            onCreate={(v) => createModule.mutateAsync(v)}
            onUpdate={(row, v) => updateModule.mutateAsync({ id: row.id, body: v })}
            onDelete={(row) => deleteModule.mutate(row.id)}
          />
        </Card>
      </Col>
      <Col span={24}>
        <Card title="Version" extra={<Link to={`/suts/${sutId}/versions`}>Manage versions</Link>}>
          {(versions.data || []).map((v) => (
            <Tag key={v.id} style={{ padding: "4px 8px" }}>
              <Link to={`/versions/${v.id}`}>{v.name}</Link> <VersionStatusTag status={v.status} />
            </Tag>
          ))}
          {versions.data?.length === 0 && (
            <EmptyState
              title="No version yet"
              hint="A version is a batch of requirements to test. Create a version, enter requirements, confirm and freeze them, then create a strategy, generate cases and run them."
              actionLabel="New version"
              onAction={() => navigate(`/suts/${sutId}/versions?new=1`)}
            />
          )}
        </Card>
      </Col>
    </Row>
  );
}
