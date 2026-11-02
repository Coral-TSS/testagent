import {
  ArrowLeftOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  BugOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  SettingOutlined,
  TeamOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Breadcrumb, Button, Layout as AntLayout, Menu, Select, Space, Tooltip, Typography } from "antd";
import type { ReactNode } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { NavContext, Sut, SutProgress } from "../api/types";
import { FlowSteps } from "../components/FlowSteps";
import { routeObject, withContext } from "./navContext";

const { Sider, Header, Content } = AntLayout;

/** Where "Back" goes when there is no in-app history (opened from a link / new tab): the parent crumb. */
export function parentPath(pathname: string, crumbs: { path: string }[]): string {
  const paths = crumbs.map((c) => c.path).filter((p) => p && p.split("?")[0] !== pathname);
  if (paths.length) return paths[paths.length - 1];
  const parts = pathname.split("/").filter(Boolean);
  return parts.length > 1 ? `/${parts.slice(0, -1).join("/")}` : "/suts";
}

/** Back: history-aware — goes back inside the app, otherwise to the parent page. */
export function BackButton({ fallback }: { fallback: string }) {
  const navigate = useNavigate();
  const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
  return (
    <Tooltip title={idx > 0 ? "Back to the previous page" : "Back to the parent page"}>
      <Button
        aria-label="Back"
        size="small"
        icon={<ArrowLeftOutlined />}
        onClick={() => (idx > 0 ? navigate(-1) : navigate(fallback))}
      >
        Back
      </Button>
    </Tooltip>
  );
}

/** Current object, SUT and version of the page (from the path, the query string or the object itself). */
export function useNavState() {
  const location = useLocation();
  const obj = routeObject(location.pathname, location.search);
  const ctx = useQuery({
    queryKey: ["nav-context", obj.kind, obj.id],
    queryFn: () => api<NavContext>("/nav/context", { params: { kind: obj.kind, id: obj.id } }),
    enabled: Boolean(obj.kind && obj.id),
    retry: false,
  });
  const sutId = obj.sutId || ctx.data?.sut?.id;
  const versionId = obj.versionId || ctx.data?.version?.id;
  const progress = useQuery({
    queryKey: ["progress", sutId, versionId || null],
    queryFn: () => api<SutProgress>(`/suts/${sutId}/progress`, { params: { version_id: versionId } }),
    enabled: Boolean(sutId),
    retry: false,
  });
  return { obj, ctx: ctx.data, sutId, versionId: versionId || progress.data?.version?.id, progress: progress.data };
}

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { obj, ctx, sutId, versionId, progress } = useNavState();
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const sutName = progress?.sut.code || ctx?.sut?.code;
  const vq = versionId ? `?version_id=${versionId}` : "";

  const items: { key: string; icon: ReactNode; label: ReactNode; children?: unknown[] }[] = [
    { key: "/suts", icon: <AppstoreOutlined />, label: <Link to="/suts">SUT</Link> },
  ];
  if (sutId) {
    items.push({
      key: `sut-${sutId}`,
      icon: <ApartmentOutlined />,
      label: sutName || "…",
      children: [
        { key: `/suts/${sutId}`, label: <Link to={`/suts/${sutId}${vq}`}>Overview</Link> },
        { key: `/suts/${sutId}/model`, label: <Link to={`/suts/${sutId}/model${vq}`}>Model</Link> },
        { key: `/suts/${sutId}/review`, label: <Link to={`/suts/${sutId}/review${vq}`}>Model review</Link> },
        { key: `/suts/${sutId}/apis`, label: <Link to={`/suts/${sutId}/apis${vq}`}>API registry</Link> },
        { key: `/suts/${sutId}/versions`, label: <Link to={`/suts/${sutId}/versions${vq}`}>Version</Link> },
        { key: `/suts/${sutId}/cases`, label: <Link to={`/suts/${sutId}/cases${vq}`}>Case library</Link> },
      ],
    });
  }
  const global = (path: string, icon: ReactNode, label: string) => ({
    key: path,
    icon,
    label: <Link to={withContext(path, sutId, versionId)}>{label}</Link>,
  });
  items.push(
    global("/cases", <ExperimentOutlined />, "Test cases"),
    global("/executions", <PlayCircleOutlined />, "Execution"),
    global("/reports", <FileTextOutlined />, "Report"),
    global("/defects", <BugOutlined />, "Defect"),
    { key: "/persons", icon: <TeamOutlined />, label: <Link to="/persons">Person</Link> },
    { key: "/stats/people", icon: <BarChartOutlined />, label: <Link to="/stats/people">People stats</Link> },
    { key: "/agent/config", icon: <SettingOutlined />, label: <Link to="/agent/config">Agent settings</Link> },
    { key: "/agent/runs", icon: <RobotOutlined />, label: <Link to="/agent/runs">Agent runs</Link> },
    { key: "/agent/tools", icon: <ToolOutlined />, label: <Link to="/agent/tools">Agent tools</Link> },
  );

  const crumbs = [
    { title: <Link to="/suts">Home</Link> },
    ...(ctx?.crumbs || []).map((c, i, all) => ({
      title: i === all.length - 1 && !obj.page ? <span>{c.label}</span> : <Link to={c.path}>{c.label}</Link>,
    })),
    ...(obj.page ? [{ title: <span>{obj.page}</span> }] : []),
  ];

  const onSut = (id: string) => navigate(`/suts/${id}`);
  const onVersion = (id: string) => {
    if (location.pathname.startsWith("/suts/") || ["/cases", "/defects", "/reports", "/executions"].includes(location.pathname)) {
      const q = new URLSearchParams(location.search);
      q.set("version_id", id);
      if (location.pathname === "/defects" || location.pathname === "/reports") q.set("sut_id", sutId || "");
      navigate(`${location.pathname}?${q.toString()}`);
    } else navigate(`/versions/${id}`);
  };

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <Sider width={220} theme="light" style={{ borderRight: "1px solid #f0f0f0" }}>
        <div style={{ padding: "16px 20px" }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            TestAgent
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={sutId ? [`sut-${sutId}`] : []}
          key={sutId || "none"}
          items={items as never}
        />
      </Sider>
      <AntLayout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            borderBottom: "1px solid #f0f0f0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          <Space size={12}>
            {location.pathname !== "/suts" && location.pathname !== "/" && (
              <BackButton fallback={parentPath(location.pathname, ctx?.crumbs || [])} />
            )}
            <Breadcrumb data-testid="breadcrumbs" items={crumbs} />
          </Space>
          <Space style={{ flexShrink: 0 }}>
            <Typography.Text type="secondary" style={{ whiteSpace: "nowrap" }}>
              Current
            </Typography.Text>
            <Select
              aria-label="Current SUT"
              placeholder="Choose SUT"
              style={{ width: 200 }}
              value={sutId}
              onChange={onSut}
              options={(suts.data || []).map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))}
            />
            <Select
              aria-label="Current version"
              placeholder={sutId ? "Choose version" : "Choose a SUT first"}
              disabled={!sutId || !progress?.versions.length}
              style={{ width: 140 }}
              value={progress?.version?.id}
              onChange={onVersion}
              options={(progress?.versions || []).map((v) => ({ value: v.id, label: `Version ${v.name}` }))}
            />
          </Space>
        </Header>
        {progress && (
          <div style={{ background: "#fff", padding: "10px 24px", borderBottom: "1px solid #f0f0f0" }}>
            <FlowSteps progress={progress} />
          </div>
        )}
        <Content style={{ padding: 24 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
