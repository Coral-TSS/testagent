import { CloseOutlined } from "@ant-design/icons";
import { Button, Space } from "antd";
import type { ReactNode } from "react";

import { useRememberedWidth } from "./width";

/** Docked detail panel: no mask, resizable, sticky 取消 / 保存. The page beside it stays usable. */
export function SideDetailPanel({
  kind = "node",
  title,
  extra,
  children,
  onClose,
  onCancel,
  onSave,
  saving,
  defaultWidth = 520,
  footer,
}: {
  kind?: string;
  title: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  onClose: () => void;
  onCancel?: () => void;
  onSave?: () => void;
  saving?: boolean;
  defaultWidth?: number;
  /** Pass null to hide the footer (read-only). */
  footer?: ReactNode | null;
}) {
  const width = useRememberedWidth(`testagent:drawer-width:${kind}`, () => defaultWidth);
  return (
    <aside
      className={["side-detail-panel", width.resizing ? "side-detail-resizing" : ""].filter(Boolean).join(" ")}
      style={{ width: width.compact ? "100%" : width.width }}
      data-testid="side-detail-panel"
      aria-label={typeof title === "string" ? title : "详情"}
    >
      {width.handle}
      <div className="side-detail-head">
        <div className="side-detail-title">{title}</div>
        <Space size={8}>
          {extra}
          <Button aria-label="关闭" type="text" icon={<CloseOutlined />} onClick={onClose} />
        </Space>
      </div>
      <div className="side-detail-body">{children}</div>
      {footer !== null && (
        <div className="side-detail-footer">
          {footer ?? (
            <>
              <Button onClick={onCancel || onClose}>取消</Button>
              <Button type="primary" loading={saving} onClick={onSave}>
                保存
              </Button>
            </>
          )}
        </div>
      )}
    </aside>
  );
}
