import { Modal, Typography, type ModalProps } from "antd";
import type { ReactNode } from "react";

/** The only three dialog widths used by the product. */
export const MODAL_WIDTH = { sm: 520, md: 720, lg: 960 } as const;
export type ModalSize = keyof typeof MODAL_WIDTH;

/** Dialog with a fixed width, optional help under the title, and 保存 as the default confirm. */
export function AppModal({
  size = "sm",
  help,
  title,
  okText = "保存",
  cancelText = "取消",
  ...props
}: ModalProps & { size?: ModalSize; help?: ReactNode }) {
  return (
    <Modal
      width={MODAL_WIDTH[size]}
      okText={okText}
      cancelText={cancelText}
      title={
        help ? (
          <div>
            <div>{title}</div>
            <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 13 }}>
              {help}
            </Typography.Text>
          </div>
        ) : (
          title
        )
      }
      {...props}
    />
  );
}
