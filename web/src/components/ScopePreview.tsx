import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Input, Select, Space, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ScopeManifest, ScopeSnapshot, ScopeTarget } from "../api/types";

const ORIGIN: Record<string, string> = { seed: "种子", expanded: "扩展", manual: "手动" };
const DEPTHS = [
  { value: 0, label: "0 只含已引用" },
  { value: 1, label: "1 向外一层" },
  { value: 2, label: "2 再向外一层" },
];

type NodeRow = { id: string; kind: string; name: string };

function targetText(target: ScopeTarget): string {
  return target.text || target.when || target.then || target.label || [target.entity, target.name].filter(Boolean).join(".") || target.action || target.id;
}

/** Scope the tester confirms before case generation. Edits stay on the snapshot. */
export function ScopePreview({
  versionId,
  sutId,
  requirementIds,
  onReady,
}: {
  versionId: string;
  sutId: string;
  requirementIds: string[];
  onReady: (ready: boolean) => void;
}) {
  const [scopes, setScopes] = useState<ScopeSnapshot[]>([]);
  const [waiverFor, setWaiverFor] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const nodes = useQuery({
    queryKey: ["nodes", sutId, versionId],
    queryFn: () => api<NodeRow[]>(`/suts/${sutId}/nodes`, { params: { version_id: versionId } }),
  });

  const load = async (ids: string[]) => {
    setBusy(true);
    setError(undefined);
    try {
      const body = await api<{ scopes: ScopeSnapshot[] }>(`/versions/${versionId}/case-gen/scope`, {
        method: "POST",
        body: { requirement_ids: ids.length ? ids : null },
      });
      setScopes(body.scopes);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load(requirementIds);
    // recompute when the chosen requirements change; edits are per snapshot
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId, requirementIds.join("|")]);

  const replace = (next: ScopeSnapshot) => setScopes((prev) => prev.map((s) => (s.requirement_id === next.requirement_id ? next : s)));

  const edit = async (requirementId: string, body: Record<string, unknown>) => {
    setBusy(true);
    try {
      const out = await api<{ scopes: ScopeSnapshot[] }>(`/versions/${versionId}/case-gen/scope`, {
        method: "PUT",
        body: { requirement_id: requirementId, ...body },
      });
      if (out.scopes[0]) replace(out.scopes[0]);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    const ids = scopes.filter((s) => s.id).map((s) => s.requirement_id);
    if (!ids.length) return;
    setBusy(true);
    try {
      const out = await api<{ scopes: ScopeSnapshot[] }>(`/versions/${versionId}/case-gen/scope/confirm`, {
        method: "POST",
        body: { requirement_ids: ids },
      });
      setScopes(out.scopes);
    } finally {
      setBusy(false);
    }
  };

  const blocked = scopes.some((s) => s.manifest.blocked || !s.id);
  const ready = scopes.length > 0 && !blocked && scopes.every((s) => s.confirmed);
  useEffect(() => {
    onReady(ready);
  }, [ready, onReady]);

  const rowsOf = (manifest: ScopeManifest) => [
    ...(manifest.nodes || []).map((n) => ({ key: n.id, kind: n.kind, id: n.id, name: n.name, origin: n.origin, note: n.far_side ? "远侧" : "" })),
    ...(manifest.fields || []).map((f) => ({ key: f.id, kind: "field", id: f.id, name: `${f.entity}.${f.name}`, origin: f.origin, note: f.far_side ? "远侧" : "" })),
    ...(manifest.links || []).map((l) => ({ key: l.id, kind: "link", id: l.id, name: l.name, origin: l.origin, note: l.required ? "必填" : "可空" })),
    ...(manifest.apis || []).map((a) => ({ key: a.id, kind: "api", id: a.id, name: `${a.method} ${a.path}`, origin: a.origin || "expanded", note: "" })),
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size={12} data-testid="scope-preview">
      {error && <Alert type="error" message={error} />}
      {scopes.map((scope) => {
        const manifest = scope.manifest;
        const code = manifest.requirement?.code || scope.requirement_id;
        if (manifest.blocked || !scope.id) {
          return <Alert key={scope.requirement_id} type="error" showIcon message={scope.message || manifest.message || `${code} 没有结构化引用，不能生成用例`} />;
        }
        const present = new Set(rowsOf(manifest).map((r) => r.id));
        return (
          <div key={scope.requirement_id}>
            <Space wrap style={{ marginBottom: 8 }}>
              <Typography.Text strong>{code} {manifest.requirement?.title}</Typography.Text>
              {scope.confirmed ? <Tag color="green">已确认</Tag> : <Tag>未确认</Tag>}
              <Select
                aria-label={`${code} 的范围深度`}
                style={{ width: 160 }}
                value={scope.depth}
                options={DEPTHS}
                onChange={(depth) => edit(scope.requirement_id, { depth, recompute: true })}
              />
            </Space>
            <Table
              size="small"
              pagination={false}
              rowKey="key"
              dataSource={rowsOf(manifest)}
              columns={[
                { title: "名称", dataIndex: "name" },
                { title: "来源", dataIndex: "origin", width: 80, render: (o: string) => ORIGIN[o] || o },
                { title: "说明", dataIndex: "note", width: 80 },
                {
                  title: "",
                  width: 72,
                  render: (_, row) => (
                    <Button size="small" data-testid={`remove-${row.id}`} onClick={() => edit(scope.requirement_id, { remove: [{ kind: row.kind, id: row.id }] })}>
                      去掉
                    </Button>
                  ),
                },
              ]}
            />
            <Select
              aria-label={`${code} 加入对象`}
              placeholder="加入范围外的对象"
              style={{ width: "100%", marginTop: 8 }}
              options={(nodes.data || [])
                .filter((n) => n.kind !== "relation" && !present.has(n.id))
                .map((n) => ({ value: `${n.kind}:${n.id}`, label: `${n.kind === "action" ? "动作" : "实体"} ${n.name}` }))}
              onChange={(value: string) => {
                const [kind, id] = value.split(":");
                edit(scope.requirement_id, { add: [{ kind, id }] });
              }}
            />
            <Typography.Paragraph type="secondary" style={{ margin: "8px 0 4px" }}>覆盖目标</Typography.Paragraph>
            <Table
              size="small"
              pagination={false}
              rowKey="id"
              dataSource={manifest.targets || []}
              columns={[
                { title: "类型", dataIndex: "type", width: 160 },
                { title: "目标", render: (_, t: ScopeTarget) => targetText(t) },
                {
                  title: "",
                  width: 220,
                  render: (_, t: ScopeTarget) =>
                    waiverFor === t.id ? (
                      <Input
                        size="small"
                        placeholder="不覆盖的理由"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        onPressEnter={() => {
                          if (reason.trim()) edit(scope.requirement_id, { waivers: [{ target_id: t.id, reason: reason.trim() }] });
                          setWaiverFor(null);
                          setReason("");
                        }}
                      />
                    ) : (
                      <Button size="small" onClick={() => setWaiverFor(t.id)}>不覆盖</Button>
                    ),
                },
              ]}
            />
          </div>
        );
      })}
      <Button type="primary" disabled={blocked || !scopes.some((s) => s.id)} loading={busy} onClick={confirm}>
        确认范围
      </Button>
    </Space>
  );
}
