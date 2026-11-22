import {
  ArrowLeftOutlined,
  ApartmentOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  BugOutlined,
  FileTextOutlined,
  PlayCircleOutlined,
  ProjectOutlined,
  RobotOutlined,
  SettingOutlined,
  TeamOutlined,
  ToolOutlined,
  UserOutlined,
  UsergroupAddOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Breadcrumb, Button, Dropdown, Layout as AntLayout, Menu, Modal, Select, Space, Tooltip, Typography } from "antd";
import { useEffect, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { NavContext, Sut, SutProgress } from "../api/types";
import { FlowSteps } from "../components/FlowSteps";
import { ChangePasswordForm, useAuth } from "./AuthGate";
import { routeObject, withContext } from "./navContext";
import { menuSelection, sutLinks, switchSutTarget, switchVersionTarget } from "./navMenu";

const { Sider, Header, Content } = AntLayout;

/** Where "返回" goes when there is no in-app history (opened from a link / new tab): the parent crumb. */
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
    <Tooltip title={idx > 0 ? "返回上一页" : "返回上级页面"}>
      <Button
        aria-label="返回"
        size="small"
        icon={<ArrowLeftOutlined />}
        onClick={() => (idx > 0 ? navigate(-1) : navigate(fallback))}
      >
        返回
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

/** Signed-in user: change password, sign out (hidden outside the auth gate, e.g. in page tests). */
export function UserMenu() {
  const { me, signOut, refresh } = useAuth();
  const [changing, setChanging] = useState(false);
  if (!me) return null;
  const roleLabel = me.role === "admin" ? "管理员" : me.role === "member" ? "成员" : me.role;
  return (
    <>
      <Dropdown
        trigger={["click"]}
        menu={{
          items: [
            { key: "role", label: `${me.username} · ${roleLabel}`, disabled: true },
            { type: "divider" },
            { key: "password", label: "修改密码", onClick: () => setChanging(true) },
            { key: "logout", label: "退出登录", onClick: () => void signOut() },
          ],
        }}
      >
        <Button aria-label="账户" icon={<UserOutlined />}>
          {me.display_name || me.username}
        </Button>
      </Dropdown>
      <Modal title="修改密码" open={changing} footer={null} onCancel={() => setChanging(false)} destroyOnHidden>
        <Typography.Paragraph type="secondary">你的其他会话已退出；当前会话保持登录。</Typography.Paragraph>
        <ChangePasswordForm
          onDone={(next) => {
            refresh(next);
            setChanging(false);
          }}
        />
      </Modal>
    </>
  );
}

function disabledItem(key: string, label: string, tip: string) {
  return {
    key,
    disabled: true,
    label: (
      <Tooltip title={tip}>
        <span className="nav-hint">{label}</span>
      </Tooltip>
    ),
  };
}

function linkItem(key: string, to: string, label: string, icon?: ReactNode) {
  return { key, icon, label: <Link to={to}>{label}</Link> };
}

export function Layout() {
  const { me } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const { obj, ctx, sutId, versionId, progress } = useNavState();
  const suts = useQuery({ queryKey: ["suts"], queryFn: () => api<Sut[]>("/suts") });
  const links = sutId ? sutLinks(sutId, versionId) : null;
  const selected = menuSelection(location.pathname, location.search, sutId);
  const [openKeys, setOpenKeys] = useState<string[]>(["nav-current", "nav-model"]);
  useEffect(() => {
    setOpenKeys((keys) => {
      const next = new Set(keys);
      next.add("nav-current");
      if (selected.startsWith("model-")) next.add("nav-model");
      return [...next];
    });
  }, [selected]);

  const chooseTip = "请先选择被测系统";
  const versionTip = "请先创建版本";
  const stopMenu = (e: ReactMouseEvent) => {
    e.stopPropagation();
  };
  const switcher = (label: string, node: ReactNode) => ({
    key: label,
    label: (
      <div onClick={stopMenu} onMouseDown={stopMenu}>
        {node}
      </div>
    ),
  });
  const modelChildren = versionId && links
    ? [
        linkItem("model-graph", links.model, "模型图谱"),
        linkItem("model-apis", links.apis, "API 注册表"),
      ]
    : [
        disabledItem("model-graph", "模型图谱", sutId ? versionTip : chooseTip),
        disabledItem("model-apis", "API 注册表", sutId ? versionTip : chooseTip),
      ];
  const workflowTip = sutId ? versionTip : chooseTip;
  const currentChildren = [
    switcher(
      "sut-switcher",
      <Select
        aria-label="切换被测系统"
        size="small"
        style={{ width: "100%" }}
        placeholder="选择被测系统"
        value={sutId}
        onChange={(id) => navigate(switchSutTarget(location.pathname, location.search, id))}
        options={(suts.data || []).map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))}
      />,
    ),
    switcher(
      "version-switcher",
      <Select
        aria-label="切换当前版本"
        size="small"
        style={{ width: "100%" }}
        placeholder={sutId ? "请先创建版本" : "请先选择被测系统"}
        disabled={!sutId || !progress?.versions.length}
        value={progress?.version?.id}
        onChange={(id) => navigate(switchVersionTarget(location.pathname, location.search, id, sutId))}
        options={(progress?.versions || []).map((v) => ({ value: v.id, label: `版本 ${v.name}` }))}
      />,
    ),
    sutId && links ? linkItem("sut-overview", links.overview, "概览") : disabledItem("sut-overview", "概览", chooseTip),
    versionId && links
      ? { key: "nav-model", icon: <ApartmentOutlined />, label: "建模", children: modelChildren }
      : disabledItem("nav-model", "建模", workflowTip),
    versionId && links ? linkItem("sut-requirements", links.requirements, "版本与需求") : disabledItem("sut-requirements", "版本与需求", workflowTip),
    versionId && links ? linkItem("sut-strategy", links.strategy, "策略") : disabledItem("sut-strategy", "策略", workflowTip),
    versionId && links ? linkItem("sut-tasks", links.tasks, "任务") : disabledItem("sut-tasks", "任务", workflowTip),
    sutId && links ? linkItem("sut-cases", links.cases, "用例") : disabledItem("sut-cases", "用例", chooseTip),
  ];

  const items = [
    linkItem("sut-list", "/suts", "全部被测系统", <AppstoreOutlined />),
    { key: "nav-current", icon: <ProjectOutlined />, label: "当前系统", children: currentChildren },
    linkItem("global-executions", "/executions", "执行", <PlayCircleOutlined />),
    linkItem("global-defects", "/defects", "缺陷", <BugOutlined />),
    linkItem("global-reports", withContext("/reports", sutId, versionId), "测试报告", <FileTextOutlined />),
    {
      type: "group" as const,
      label: "人员",
      children: [
        linkItem("persons", "/persons", "人员", <TeamOutlined />),
        linkItem("people-stats", "/stats/people", "人员统计", <BarChartOutlined />),
      ],
    },
    {
      type: "group" as const,
      label: "Agent",
      children: [
        linkItem("agent-config", "/agent/config", "设置", <SettingOutlined />),
        linkItem("agent-runs", "/agent/runs", "运行", <RobotOutlined />),
        linkItem("agent-tools", "/agent/tools", "工具", <ToolOutlined />),
      ],
    },
    ...(me?.role === "admin" ? [linkItem("users", "/users", "用户", <UsergroupAddOutlined />)] : []),
  ];

  const crumbs = [
    { title: <Link to="/suts">首页</Link> },
    ...(ctx?.crumbs || []).map((c, i, all) => ({
      title: i === all.length - 1 && !obj.page ? <span>{c.label}</span> : <Link to={c.path}>{c.label}</Link>,
    })),
    ...(obj.page ? [{ title: <span>{obj.page}</span> }] : []),
  ];

  const onSut = (id: string) => navigate(switchSutTarget(location.pathname, location.search, id));
  const onVersion = (id: string) => navigate(switchVersionTarget(location.pathname, location.search, id, sutId));

  return (
    <AntLayout style={{ minHeight: "100vh" }}>
      <Sider
        width={240}
        theme="light"
        style={{ borderRight: "1px solid #f0f0f0", position: "sticky", top: 0, height: "100vh", overflow: "auto" }}
      >
        <div style={{ padding: "16px 20px" }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            TestAgent
          </Typography.Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={selected ? [selected] : []}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={items}
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
              当前
            </Typography.Text>
            <Select
              aria-label="当前被测系统"
              placeholder="选择被测系统"
              style={{ width: 200 }}
              value={sutId}
              onChange={onSut}
              options={(suts.data || []).map((s) => ({ value: s.id, label: `${s.name} (${s.code})` }))}
            />
            <Select
              aria-label="当前版本"
              placeholder={sutId ? "选择版本" : "请先选择被测系统"}
              disabled={!sutId || !progress?.versions.length}
              style={{ width: 140 }}
              value={progress?.version?.id}
              onChange={onVersion}
              options={(progress?.versions || []).map((v) => ({ value: v.id, label: `版本 ${v.name}` }))}
            />
            <UserMenu />
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
