import { App, Button, Checkbox, Input, List, Select, Space, Switch, Tag, Tooltip, Typography } from "antd";
import { useMemo, useState } from "react";

import { api, describeError } from "../api/client";
import type { AcceptBatchResult, CompletionOutcome, DataType, Suggestion, SuggestionSource } from "../api/types";
import { DATA_TYPE_LABEL } from "./EntityFields";
import { CARD_LABEL, CARD_SHORT, effectText, preconditionText } from "./links";
import { LIST_HEIGHT, ListCount, listTitle } from "./ListView";

const ATTR: Record<string, string> = { conditions: "条件", states: "状态", constraints: "约束" };
const KIND: Record<string, string> = { entity: "实体", action: "动作", relation: "关系" };

export function describeSuggestion(s: Suggestion): string {
  const p = s.payload;
  if (s.kind === "node") return `新增${KIND[p.node_kind || ""] || "节点"}“${p.name}”`;
  const owner = p.node_name || "（未知节点）"; // the server fills node_name; never show a UUID
  if (s.kind === "field") {
    const type = p.data_type ? `, ${DATA_TYPE_LABEL[p.data_type as DataType] || p.data_type}` : "";
    const values = p.enum_values?.length ? ` (${p.enum_values.join("/")})` : "";
    const unit = p.unit ? `，单位 ${p.unit}` : "";
    if (p.rename_from)
      return `“${owner}”的字段 ${p.rename_from} 已重命名为 ${p.name}（与 API 字段一致，关系保留）${type}${values}${unit}`;
    return `添加到“${owner}”新字段 ${p.name}${p.display_name ? `（${p.display_name}）` : ""}${type}${values}${unit}`;
  }
  if (s.kind === "link") {
    const from = p.from_name || "?";
    const to = p.to_name || "?";
    const card = p.cardinality ? CARD_SHORT[p.cardinality] : "N:1";
    const fk = p.fk_field ? `，外键 ${p.fk_field}` : "";
    return `新建关系“${from} ${p.forward_name || "相关"} ${to}” / “${to} ${p.reverse_name || "相关"} ${from}”（${card}${fk}）`;
  }
  if (s.kind === "rules") {
    const parts = [
      p.preconditions?.length ? `前置条件 ${p.preconditions.map(preconditionText).join("；")}` : "",
      p.effects?.length ? `效果 ${p.effects.map((e) => effectText(e)).join("；")}` : "",
    ].filter(Boolean);
    return `添加到动作“${owner}”：${parts.join("；")}`;
  }
  if (s.kind === "io") {
    const parts = [
      p.description ? `用途：${p.description}` : "",
      p.inputs?.length ? `输入 ${p.inputs.map((x) => x.name).join("，")}` : "",
      p.outputs?.length ? `输出 ${p.outputs.map((x) => x.name).join("，")}` : "",
    ].filter(Boolean);
    return `添加到动作“${owner}”：${parts.join("；") || "输入/输出"}`;
  }
  return `添加到“${owner}”：${ATTR[p.attr || ""] || p.attr}：${p.text}`;
}

/** #6: where a suggestion comes from → label and colour. */
export const SOURCE_TAG: Record<SuggestionSource, [string, string]> = {
  requirement: ["需求", "blue"],
  openapi: ["OpenAPI", "green"],
  model_rule: ["模型规则", "cyan"],
  ai_inferred: ["AI 推断", "orange"],
};

/** Pre-selected for "Accept selected": pending, not an AI inference, not a link (links need their names confirmed). */
export function defaultSelected(items: Suggestion[]): string[] {
  return items.filter((s) => s.status === "pending" && (s.source || "ai_inferred") !== "ai_inferred" && s.kind !== "link").map((s) => s.id);
}

const DROP_LABEL: Record<string, string> = {
  duplicate_node: "模型中已存在",
  duplicate_api: "API 已绑定到动作",
  duplicate_in_batch: "本批次中重复",
  previously_rejected: "此前已拒绝",
  invalid: "缺少名称或描述",
};

/** #4: "3 new suggestions, 4 left out (2 repeated in the same batch, 1 API already bound…)". */
export function completionNote(out: CompletionOutcome): string | null {
  if (!out.suggestions) return null;
  const parts = Object.entries(out.dropped || {})
    .filter(([, n]) => (n || 0) > 0)
    .map(([k, n]) => `${n} ${DROP_LABEL[k] || k}`);
  const skipped = out.skipped || 0;
  const pending = skipped - Object.values(out.dropped || {}).reduce((a, n) => a + (n || 0), 0);
  if (pending > 0) parts.push(`${pending} 条已在待处理中`);
  return `${out.suggestions.length} 条新建议${skipped ? `，排除 ${skipped} 条（${parts.join("，")}）` : ""}`;
}

function SourceTag({ s }: { s: Suggestion }) {
  const source = s.source || "ai_inferred";
  const [label, color] = SOURCE_TAG[source];
  const text = source === "requirement" && s.requirement_code ? `${label} ${s.requirement_code}` : label;
  return (
    <Tooltip title={s.evidence ? `依据：${s.evidence}` : source === "ai_inferred" ? "无来源：由 AI 推断" : undefined}>
      <Tag color={color}>{text}</Tag>
    </Tooltip>
  );
}

/** Accept/reject model suggestions (human-only; agent output never lands without this). */
export function SuggestionList({ sutId, items, onChanged, loading, error, onRetry }: {
  sutId: string; items: Suggestion[]; onChanged: () => void; loading?: boolean; error?: boolean; onRetry?: () => void;
}) {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [onlyAi, setOnlyAi] = useState(false);
  const pending = items.filter((s) => s.status === "pending");
  const selected = useMemo(() => (picked ?? defaultSelected(items)).filter((id) => pending.some((s) => s.id === id)), [picked, items, pending]);
  const shown = onlyAi ? items.filter((s) => (s.source || "ai_inferred") === "ai_inferred") : items;
  const run = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id);
    try {
      await fn();
      message.success(ok);
      onChanged();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };
  const reject = (s: Suggestion) => {
    let reason = "";
    modal.confirm({
      title: "拒绝建议",
      content: <Input.TextArea placeholder="原因（可选，用于引导后续建议）" onChange={(e) => (reason = e.target.value)} />,
      onOk: () => run(s.id, () => api(`/suggestions/${s.id}/reject`, { method: "POST", body: { reason: reason || null } }), "已拒绝"),
    });
  };
  const inferred = (s: Suggestion) => (s.source || "ai_inferred") === "ai_inferred";
  type Dialog = { current: { update: (c: { okButtonProps: { disabled: boolean } }) => void } | null };
  /** an AI inference needs the person's reason (5+ characters): OK stays disabled until then */
  const noteField = (s: Suggestion, v: { note?: string }, dialog: Dialog) =>
    inferred(s) ? (
      <Input.TextArea
        aria-label="为何正确"
        placeholder="无来源的 AI 推断：为何正确？（不少于 5 个字符，会记入变更日志）"
        onChange={(e) => {
          v.note = e.target.value.trim();
          dialog.current?.update({ okButtonProps: { disabled: v.note.length < 5 } });
        }}
        style={{ marginTop: 8 }}
      />
    ) : null;
  const gate = (s: Suggestion) => ({ okButtonProps: { disabled: inferred(s) } });
  const accept = (s: Suggestion) => {
    if (s.kind === "link") {
      const p = s.payload;
      const initial = {
        forward_name: p.forward_name || "belongs to",
        reverse_name: p.reverse_name || "has",
        forward_api_name: p.forward_api_name || undefined,
        reverse_api_name: p.reverse_api_name || undefined,
        cardinality: p.cardinality || "many_to_one",
      };
      const v: Record<string, string | undefined> = { ...initial };
      const set = (k: string) => (e: { target: { value: string } }) => (v[k] = e.target.value.trim() || undefined);
      const dialog: Dialog = { current: null };
      dialog.current = modal.confirm({
        ...gate(s),
        title: "接受关系建议（如需可先修改读法）",
        width: 560,
        content: (
          <Space orientation="vertical" style={{ width: "100%", marginTop: 12 }}>
            <span>
              {p.from_name} <Input size="small" style={{ width: 120 }} defaultValue={initial.forward_name} onChange={set("forward_name")} aria-label="正向名称" /> {p.to_name}
            </span>
            <span>
              {p.to_name} <Input size="small" style={{ width: 120 }} defaultValue={initial.reverse_name} onChange={set("reverse_name")} aria-label="反向名称" /> {p.from_name}
            </span>
            <span>
              API 名称：
              <Input size="small" style={{ width: 140 }} defaultValue={initial.forward_api_name} onChange={set("forward_api_name")} /> /{" "}
              <Input size="small" style={{ width: 140 }} defaultValue={initial.reverse_api_name} onChange={set("reverse_api_name")} />
            </span>
            <Select
              size="small"
              style={{ width: 260 }}
              defaultValue={initial.cardinality}
              onChange={(c) => (v.cardinality = c)}
              options={Object.entries(CARD_LABEL).map(([value, label]) => ({ value, label }))}
            />
            {p.fk_field && <Typography.Text type="secondary">外键 {p.fk_field}</Typography.Text>}
            {noteField(s, v, dialog)}
          </Space>
        ),
        onOk: () => {
          if (!v.forward_name || !v.reverse_name) {
            message.error("两个方向的名称都必填");
            return Promise.reject(new Error("需要填写名称"));
          }
          return run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: v }), "已接受并创建关系");
        },
      });
      return;
    }
    if (s.kind !== "node") {
      if (!inferred(s)) {
        run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: {} }), "已接受");
        return;
      }
      const v: { note?: string } = {};
      const dialog: Dialog = { current: null };
      dialog.current = modal.confirm({
        ...gate(s),
        title: "接受 AI 推断",
        content: (
          <>
            <Typography.Paragraph style={{ marginBottom: 0 }}>{describeSuggestion(s)}</Typography.Paragraph>
            {noteField(s, v, dialog)}
          </>
        ),
        onOk: () => run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: v }), "已接受"),
      });
      return;
    }
    const v: { name?: string; note?: string } = { name: s.payload.name || "" };
    const dialog: Dialog = { current: null };
    dialog.current = modal.confirm({
      ...gate(s),
      title: "接受并创建节点",
      content: (
        <>
          <Input aria-label="节点名称" defaultValue={v.name} onChange={(e) => (v.name = e.target.value)} />
          {s.payload.similar_to && <Typography.Text type="warning">可能与「{s.payload.similar_to}」重复</Typography.Text>}
          {noteField(s, v, dialog)}
        </>
      ),
      onOk: () => run(s.id, () => api(`/suggestions/${s.id}/accept`, { method: "POST", body: { name: v.name, ...(v.note ? { note: v.note } : {}) } }), "已接受并创建节点"),
    });
  };
  const acceptSelected = async () => {
    setBusy("batch");
    try {
      const out = await api<AcceptBatchResult>(`/suts/${sutId}/suggestions/accept-batch`, { method: "POST", body: { ids: selected } });
      if (out.skipped.length) message.warning(`已接受 ${out.accepted.length}，跳过 ${out.skipped.length}：${[...new Set(out.skipped.map((x) => x.message))].join("；")}`);
      else message.success(`已接受 ${out.accepted.length}`);
      setPicked(null);
      onChanged();
    } catch (err) {
      message.error(describeError(err));
    } finally {
      setBusy(null);
    }
  };
  const toggle = (id: string, on: boolean) => setPicked(on ? [...selected, id] : selected.filter((x) => x !== id));
  const aiCount = pending.filter(inferred).length;
  return (
    <>
      <Typography.Text strong role="status" aria-label="模型建议数量">{listTitle("模型建议", loading || (error && !items.length) ? undefined : shown.length)}</Typography.Text>
      {pending.length > 0 && (
        <Space wrap style={{ marginBottom: 8 }} data-testid="suggestion-batch">
          <Button type="primary" size="small" disabled={!selected.length} loading={busy === "batch"} onClick={acceptSelected}>
            接受所选（{selected.length}）
          </Button>
          <Typography.Text type="secondary">AI 推断和关系不会预选：请逐条接受。</Typography.Text>
          {aiCount > 0 && (
            <Space size={4}>
              <Switch size="small" checked={onlyAi} onChange={setOnlyAi} aria-label="仅 AI 推断" />
              <span>仅 AI 推断（{aiCount}）</span>
            </Space>
          )}
        </Space>
      )}
      <div className="list-region" role="region" aria-label="模型建议列表" tabIndex={0} style={{ maxHeight: LIST_HEIGHT, overflowY: "auto" }}>
      <List
        size="small"
        dataSource={shown}
        locale={{ emptyText: loading ? "正在加载建议…" : error ? "无法获取建议" : onlyAi ? "没有符合筛选条件的建议" : "暂无建议" }}
        renderItem={(s) => (
          <List.Item
            actions={
              s.status === "pending"
                ? [
                    <a key="a" onClick={() => accept(s)} aria-disabled={busy === s.id}>
                      接受
                    </a>,
                    <a key="r" onClick={() => reject(s)}>
                      拒绝
                    </a>,
                  ]
                : [<Tag key="s">{s.status === "accepted" ? "已接受" : "已拒绝"}</Tag>]
            }
          >
            <Space align="start">
              {s.status === "pending" && (
                <Checkbox
                  aria-label={`选择 ${describeSuggestion(s)}`}
                  checked={selected.includes(s.id)}
                  disabled={s.kind === "link" || inferred(s)}
                  onChange={(e) => toggle(s.id, e.target.checked)}
                />
              )}
              <Space orientation="vertical" size={0}>
                <span>
                  <SourceTag s={s} />
                  {s.source !== "requirement" && s.requirement_code && <Tag>{s.requirement_code}</Tag>}
                  {describeSuggestion(s)}
                  {s.payload.api && <Typography.Text code>{s.payload.api}</Typography.Text>}
                  {s.payload.similar_to && <Tag color="gold">可能重复：{s.payload.similar_to}</Tag>}
                </span>
                {s.evidence && <Typography.Text type="secondary">Basis: {s.evidence}</Typography.Text>}
                {s.reason && <Typography.Text type="secondary">{s.reason}</Typography.Text>}
                {s.payload.reason && s.payload.reason !== s.reason && <Typography.Text type="secondary">{s.payload.reason}</Typography.Text>}
              </Space>
            </Space>
          </List.Item>
        )}
      />
      </div>
      <ListCount label="模型建议" count={loading || (error && !items.length) ? undefined : shown.length} total={items.length} filtered={onlyAi} error={error} onRetry={onRetry} />
    </>
  );
}
