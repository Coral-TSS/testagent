import { Button, Empty, Typography } from "antd";
import type { ReactNode } from "react";

/** Helpful empty state: what this list is for, and the main action to fill it. */
export function EmptyState({
  title,
  hint,
  actionLabel,
  onAction,
  extra,
}: {
  title: string;
  hint?: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  extra?: ReactNode;
}) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <div style={{ maxWidth: 520, margin: "0 auto" }}>
          <Typography.Text strong>{title}</Typography.Text>
          {hint && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
              {hint}
            </Typography.Paragraph>
          )}
        </div>
      }
    >
      {actionLabel && onAction && (
        <Button type="primary" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
      {extra}
    </Empty>
  );
}
