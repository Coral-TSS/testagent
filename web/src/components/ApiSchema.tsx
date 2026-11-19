import { Descriptions, Space, Tag, Typography } from "antd";

import type { ApiEndpoint, IoParam } from "../api/types";
import { IoParamsTable } from "./IoParams";

type Responses = Record<string, { description?: string | null }>;

/** P04 API detail: purpose, request format + parameter/body field table, response format + response field table (generated from the registered schema). */
export function ApiSchemaView({ api }: { api: ApiEndpoint }) {
  const io = api.io || { inputs: [] as IoParam[], outputs: [] as IoParam[] };
  const responses = (api.response_schema || {}) as Responses;
  const noSchema = !api.request_schema && !api.response_schema;
  return (
    <Space orientation="vertical" style={{ width: "100%" }} size="middle">
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="用途">
          {api.description || <Typography.Text type="secondary">未填写（点击“编辑描述和字段”说明该 API 做什么）</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="输入格式">
          {io.input_format || (api.request_content_type ? api.request_content_type : <Typography.Text type="secondary">没有请求体</Typography.Text>)}
        </Descriptions.Item>
        <Descriptions.Item label="输出格式">
          {io.output_format || api.response_content_type || <Typography.Text type="secondary">未登记</Typography.Text>}
        </Descriptions.Item>
        {Object.keys(responses).length > 0 && (
          <Descriptions.Item label="状态码">
            <Space wrap size={4}>
              {Object.entries(responses).map(([code, r]) => (
                <span key={code}>
                  <Tag color={code.startsWith("2") ? "green" : "orange"}>{code}</Tag>
                  {r?.description}
                </span>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        {api.schema_source && (
          <Descriptions.Item label="来源">{api.schema_source === "openapi" ? "OpenAPI 导入" : "手工"}</Descriptions.Item>
        )}
      </Descriptions>
      {noSchema ? (
        <Typography.Text type="secondary">尚未登记模式。请使用“从 OpenAPI 导入”，或点击“编辑描述和字段”手工填写。</Typography.Text>
      ) : (
        <>
          <div>
            <Typography.Text strong>输入（参数和请求体字段）</Typography.Text>
            <IoParamsTable value={io.inputs} showLocation emptyText="没有输入参数" />
          </div>
          <div>
            <Typography.Text strong>输出（成功响应字段）</Typography.Text>
            <IoParamsTable value={io.outputs} emptyText="尚未登记响应字段" />
          </div>
        </>
      )}
    </Space>
  );
}
