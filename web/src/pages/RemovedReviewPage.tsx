import { Button, Result } from "antd";
import { Link, useParams } from "react-router-dom";

/** Bookmarked model-review URLs. The workflow entry is gone; the API and stored marks stay. */
export function RemovedReviewPage() {
  const { versionId, sutId } = useParams();
  const back = versionId ? `/versions/${versionId}/model` : sutId ? `/suts/${sutId}` : "/suts";
  return (
    <Result
      status="info"
      title="模型评审已移除"
      subTitle="模型评审不再作为工作流的一部分。请在模型图谱中查看当前版本的模型。"
      extra={
        <Link to={back}>
          <Button type="primary">{versionId ? "返回模型图谱" : "返回"}</Button>
        </Link>
      }
    />
  );
}
