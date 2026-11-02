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
        <Descriptions.Item label="Purpose">
          {api.description || <Typography.Text type="secondary">Not filled in (click “Edit description & fields” to describe what this API does)</Typography.Text>}
        </Descriptions.Item>
        <Descriptions.Item label="Input format">
          {io.input_format || (api.request_content_type ? api.request_content_type : <Typography.Text type="secondary">No request body</Typography.Text>)}
        </Descriptions.Item>
        <Descriptions.Item label="Output format">
          {io.output_format || api.response_content_type || <Typography.Text type="secondary">not registered</Typography.Text>}
        </Descriptions.Item>
        {Object.keys(responses).length > 0 && (
          <Descriptions.Item label="Status code">
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
          <Descriptions.Item label="Source">{api.schema_source === "openapi" ? "OpenAPI import" : "Manual"}</Descriptions.Item>
        )}
      </Descriptions>
      {noSchema ? (
        <Typography.Text type="secondary">No schema registered. Use “Import from OpenAPI”, or click “Edit description & fields” to fill it in by hand.</Typography.Text>
      ) : (
        <>
          <div>
            <Typography.Text strong>Inputs (parameters and body fields)</Typography.Text>
            <IoParamsTable value={io.inputs} showLocation emptyText="No input parameters" />
          </div>
          <div>
            <Typography.Text strong>Outputs (success response fields)</Typography.Text>
            <IoParamsTable value={io.outputs} emptyText="No response fields registered" />
          </div>
        </>
      )}
    </Space>
  );
}
