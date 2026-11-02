import { App, Button, Popconfirm, Space, Tag } from "antd";
import { useState } from "react";

import { describeError } from "../api/client";

export interface BatchAction {
  key: string;
  label: string;
  /** one request per selected id */
  run: (id: string) => Promise<unknown>;
  confirm?: string;
  danger?: boolean;
  primary?: boolean;
}

/** Runs one action over each selected row in turn and reports success / failure per row.
 *  Used where the backend has per-item endpoints only (requirements, tasks, defects). */
export function BatchBar({
  selected,
  labelOf,
  actions,
  onDone,
  onClear,
  noun = " item(s)",
}: {
  selected: string[];
  labelOf: (id: string) => string;
  actions: BatchAction[];
  onDone: (okIds: string[]) => void;
  onClear: () => void;
  noun?: string;
}) {
  const { message, modal } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  if (!selected.length) return null;
  const go = async (a: BatchAction) => {
    setBusy(a.key);
    const ok: string[] = [];
    const failed: { id: string; error: string }[] = [];
    for (const id of selected) {
      try {
        await a.run(id);
        ok.push(id);
      } catch (err) {
        failed.push({ id, error: describeError(err) });
      }
    }
    setBusy(null);
    onDone(ok);
    const head = `${a.label}: succeeded ${ok.length}${failed.length ? `, failed ${failed.length}` : ""}`;
    if (failed.length)
      modal.info({
        title: head,
        width: 560,
        content: (
          <ul style={{ paddingInlineStart: 18 }}>
            {failed.map((f) => (
              <li key={f.id}>
                <Tag color="red">failed</Tag>
                {labelOf(f.id)}: {f.error}
              </li>
            ))}
          </ul>
        ),
      });
    else message.success(head);
  };
  return (
    <Space wrap data-testid="batch-bar" style={{ background: "#f6ffed", border: "1px solid #b7eb8f", borderRadius: 6, padding: "6px 12px", marginBottom: 8 }}>
      <span>
        Selected {selected.length} {noun}: 
      </span>
      {actions.map((a) =>
        a.confirm ? (
          <Popconfirm key={a.key} title={a.confirm} okButtonProps={{ danger: a.danger }} onConfirm={() => go(a)}>
            <Button size="small" danger={a.danger} type={a.primary ? "primary" : "default"} loading={busy === a.key} disabled={Boolean(busy)}>
              {a.label}
            </Button>
          </Popconfirm>
        ) : (
          <Button key={a.key} size="small" danger={a.danger} type={a.primary ? "primary" : "default"} loading={busy === a.key} disabled={Boolean(busy)} onClick={() => go(a)}>
            {a.label}
          </Button>
        ),
      )}
      <Button size="small" type="link" onClick={onClear}>
        Clear selection
      </Button>
    </Space>
  );
}
