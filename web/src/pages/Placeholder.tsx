import { Result } from "antd";

export function Placeholder({ code, title, milestone }: { code: string; title: string; milestone: string }) {
  return (
    <Result
      status="info"
      title={`${code} ${title}`}
      subTitle={code === "404" ? "请检查地址是否正确，或从左侧导航进入。" : `此页面随 ${milestone} 提供；后端 API 就绪后将接入。`}
    />
  );
}
