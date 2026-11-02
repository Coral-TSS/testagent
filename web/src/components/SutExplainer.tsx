import { Alert, Typography } from "antd";

import { PathText } from "./ObjLink";

/** Plain-language explanation of what a SUT is. */
export function SutExplainer({ repoPath, closable }: { repoPath?: string | null; closable?: boolean }) {
  return (
    <Alert
      type="info"
      showIcon
      closable={closable}
      style={{ marginBottom: 16 }}
      title="What is a “system under test”?"
      description={
        <div data-testid="sut-explainer">
          <Typography.Paragraph style={{ marginBottom: 4 }}>
            The system under test (SUT) is the software you want to test (e.g. “Procurement approval”). The platform organises all test work around it:
          </Typography.Paragraph>
          <ul style={{ margin: 0, paddingInlineStart: 20 }}>
            <li>
              <b>Environment</b>: the SUT's address (e.g. http://127.0.0.1:8766), optionally with a start command; the platform checks it is reachable before running.
            </li>
            <li>
              <b>Model</b>: which business objects the system has (entities, e.g. PurchaseOrder), what can be done (actions, e.g. Approve purchase order) and how objects relate (e.g. PurchaseOrder belongs to Supplier). The AI
              bases generated cases and automation scripts on the model, so a person needs to review it (see “Model review”).
            </li>
            <li>
              <b>Version</b>: a batch of requirements to test each time. After the requirements are confirmed and frozen, create a test strategy and tasks, generate and run cases, then look at defects and reports.
            </li>
            <li>
              <b>Local test repo</b>: the automation scripts written by the AI are stored in a git repository on this machine
              {repoPath ? (
                <>
                  : <PathText path={repoPath} />
                </>
              ) : (
                " (one per SUT; the path is on the SUT overview page)"
              )}
              . 
            </li>
          </ul>
        </div>
      }
    />
  );
}
