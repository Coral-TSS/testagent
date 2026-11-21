import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Descriptions, Form, Input, Row, Tag } from "antd";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApiMutation } from "../api/hooks";
import type { Environment, Module, Sut, SutProgress, Version } from "../api/types";
import { useAuth } from "../app/AuthGate";
import { EmptyState } from "../components/EmptyState";
import { PathText } from "../components/ObjLink";
import { OnboardingChecklist } from "../components/OnboardingChecklist";
import { SutExplainer } from "../components/SutExplainer";
import { EnvironmentStatus } from "../components/EnvironmentStatus";
import { SimpleCrud } from "../components/SimpleCrud";
import { VersionStatusTag } from "../components/StatusTags";

/** SUT overview: environments, optional groups, version list */
export function SutOverviewPage() {
  const isMember = useAuth().me?.role === "member";
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
    { invalidate: [["envs", sutId]], success: "已保存" },
  );
  const updateEnv = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/environments/${id}`, { method: "PATCH", body }),
    { invalidate: [["envs", sutId]], success: "已保存" },
  );
  const deleteEnv = useApiMutation((id: string) => api(`/environments/${id}`, { method: "DELETE" }), {
    invalidate: [["envs", sutId]],
  });
  const createModule = useApiMutation(
    (body: Record<string, unknown>) => api(`/suts/${sutId}/modules`, { method: "POST", body }),
    { invalidate: [["modules", sutId]], success: "已保存" },
  );
  const updateModule = useApiMutation(
    ({ id, body }: { id: string; body: Record<string, unknown> }) => api(`/modules/${id}`, { method: "PATCH", body }),
    { invalidate: [["modules", sutId]], success: "已保存" },
  );
  const deleteModule = useApiMutation((id: string) => api(`/modules/${id}`, { method: "DELETE" }), {
    invalidate: [["modules", sutId]],
  });

  return (
    <Row gutter={[16, 16]}>
      <Col span={24}>
        <SutExplainer repoPath={progress.data?.repo_path} closable />
      </Col>
      {search.get("need_version") === "1" && (
        <Col span={24}>
          <Alert type="warning" showIcon message="请先创建版本" description="没有版本就不能建模。请在下方版本列表中新建一个版本。" />
        </Col>
      )}
      <Col span={24}>
        <Card title={sut.data?.name || "被测系统"} loading={sut.isLoading}>
          <Descriptions column={3}>
            <Descriptions.Item label="编号">{sut.data?.code}</Descriptions.Item>
            <Descriptions.Item label="描述">{sut.data?.description || "-"}</Descriptions.Item>
            <Descriptions.Item label="快捷键">
              <Link to={progress.data?.version ? `/versions/${progress.data.version.id}/model` : `/suts/${sutId}/versions`}>模型</Link>&nbsp;·&nbsp;
              <Link to={progress.data?.version ? `/versions/${progress.data.version.id}/review` : `/suts/${sutId}/versions`}>模型评审</Link>&nbsp;·&nbsp;
              <Link to={progress.data?.version ? `/versions/${progress.data.version.id}/apis` : `/suts/${sutId}/versions`}>API 注册表</Link>
            </Descriptions.Item>
            <Descriptions.Item label="本地测试仓库（存放自动化脚本的 git 仓库）" span={3}>
              <PathText path={progress.data?.repo_path} />
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </Col>
      <Col span={24}>
        <Card
          title={`开始使用${progress.data?.version ? `（版本 ${progress.data.version.name}）` : ""}`}
          loading={progress.isLoading}
          extra={progress.data?.next ? `下一步：${progress.data.next.label}` : progress.data ? "主流程已完成" : null}
        >
          {progress.data && <OnboardingChecklist progress={progress.data} />}
        </Card>
      </Col>
      <Col span={12}>
        <Card>
          <SimpleCrud<Environment>
            error={envs.isError}
            onRetry={() => envs.refetch()}
            title="环境"
            emptyTitle="暂无环境"
            emptyHint="环境是被测系统的地址（例如 http://127.0.0.1:8766）。执行用例前平台会检查其是否可达；如果配置了启动命令，还可以一键启动。"
            rows={envs.data}
            loading={envs.isLoading}
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "地址", dataIndex: "base_url" },
              { title: "状态", width: 150, render: (_: unknown, e: Environment) => <EnvironmentStatus env={e} compact /> },
            ]}
            fields={
              <>
                <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="base_url" label="地址" rules={[{ required: true, pattern: /^https?:\/\/\S+$/, message: "以 http:// 或 https:// 开头" }]}>
                  <Input placeholder="http://127.0.0.1:8766" />
                </Form.Item>
                <Form.Item name="credential_ref" label="登录凭据引用（可选）">
                  <Input />
                </Form.Item>
                <Form.Item
                  name="start_command"
                  label="启动命令（可选，用于在本机启动被测系统；平台启动时若不可达会自动运行）"
                  extra={isMember ? "只有管理员可以更改启动命令（命令在平台服务器上运行）。" : undefined}
                >
                  <Input disabled={isMember} placeholder="uv run uvicorn examples.supply_chain.api:create_app --factory --host 127.0.0.1 --port 8766" />
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
            error={modules.isError}
            onRetry={() => modules.refetch()}
            title="分组（可选，用于按业务域组织节点）"
            emptyTitle="分组是可选的"
            emptyHint="分组只用于在模型图上按业务域过滤节点；可以不填。"
            rows={modules.data}
            loading={modules.isLoading}
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "描述", dataIndex: "description" },
            ]}
            fields={
              <>
                <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>
                <Form.Item name="description" label="描述">
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
        <Card title="版本" extra={<Link to={`/suts/${sutId}/versions`}>管理版本</Link>}>
          {(versions.data || []).map((v) => (
            <Tag key={v.id} style={{ padding: "4px 8px" }}>
              <Link to={`/versions/${v.id}`}>{v.name}</Link> <VersionStatusTag status={v.status} />
            </Tag>
          ))}
          {versions.data?.length === 0 && (
            <EmptyState
              title="暂无版本"
              hint="版本是一批待测需求。先创建版本，录入需求并确认、冻结，再创建策略、生成用例并执行。"
              actionLabel="新建版本"
              onAction={() => navigate(`/suts/${sutId}/versions?new=1`)}
            />
          )}
        </Card>
      </Col>
    </Row>
  );
}
