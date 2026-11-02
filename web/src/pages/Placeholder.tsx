import { Result } from "antd";

export function Placeholder({ code, title, milestone }: { code: string; title: string; milestone: string }) {
  return (
    <Result
      status="info"
      title={`${code} ${title}`}
      subTitle={`This page ships with ${milestone} ; it will be connected once the backend API is ready.`}
    />
  );
}
