import { App } from "antd";
import { useContext, useEffect, useRef, type Context } from "react";
import { UNSAFE_DataRouterContext, useBlocker } from "react-router-dom";

const LEAVE = { title: "有未保存的修改", content: "离开后这些修改会丢失。", okText: "放弃修改", cancelText: "继续编辑" };

/** Asks before a route change. No-ops under MemoryRouter, which has no data router. */
export function UnsavedNavigationGuard({ when }: { when: boolean }) {
  const router = useContext(UNSAFE_DataRouterContext as unknown as Context<unknown>);
  if (!router) return null;
  return <Blocked when={when} />;
}

function Blocked({ when }: { when: boolean }) {
  const blocker = useBlocker(when);
  const { modal } = App.useApp();
  const asked = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked") {
      asked.current = false;
      return;
    }
    if (asked.current) return;
    asked.current = true;
    modal.confirm({
      ...LEAVE,
      onOk: () => blocker.proceed?.(),
      onCancel: () => blocker.reset?.(),
    });
  }, [blocker, modal]);
  return null;
}

export function confirmDiscard(modal: { confirm: (opts: object) => void }): Promise<boolean> {
  return new Promise((resolve) => {
    modal.confirm({
      ...LEAVE,
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}
