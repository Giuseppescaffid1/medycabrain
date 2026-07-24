import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  fetchBenchmark,
  fetchClusterPerformance,
  fetchEngagementOverTime,
  fetchOverview,
  fetchTopContent,
} from "../api/analytics";
import type { Scope } from "../api/endpoints";
import { Spinner } from "../components/ui/primitives";
import { formatCount, mediaUrl } from "../lib/utils";

const INDIGO = "#6366f1";
const EMERALD = "#10b981";
const AMBER = "#f59e0b";
const GRID = "#27272a";
const AXIS = "#71717a";

export default function Analytics() {
  const { t } = useTranslation();
  const { scope: scopeParam } = useParams();
  const scope: Scope = scopeParam === "medyca" ? "medyca" : "competitor";

  const overview = useQuery({ queryKey: ["an-overview", scope], queryFn: () => fetchOverview(scope) });
  const time = useQuery({ queryKey: ["an-time", scope], queryFn: () => fetchEngagementOverTime(scope) });
  const top = useQuery({ queryKey: ["an-top", scope], queryFn: () => fetchTopContent(scope) });
  const clusters = useQuery({ queryKey: ["an-clusters", scope], queryFn: () => fetchClusterPerformance(scope) });
  const bench = useQuery({ queryKey: ["an-bench", scope], queryFn: () => fetchBenchmark(scope) });

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-xl font-bold text-white">{t(`scope.${scope}`)} · {t("analytics.title")}</h1>
        <p className="text-sm text-zinc-500">{t("analytics.subtitle")}</p>
      </div>

      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
        {/* KPI row */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label={t("analytics.reels")} value={overview.data?.reels} />
          <Kpi label={t("analytics.avgViews")} value={overview.data?.avg_views} fmt />
          <Kpi label={t("analytics.totalViews")} value={overview.data?.total_views} fmt />
          <Kpi label={t("analytics.topTheme")} text={overview.data?.top_theme ?? "—"} />
        </div>

        {/* Engagement over time */}
        <Card title={t("analytics.overTime")}>
          {time.isLoading ? <Spinner /> : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={time.data ?? []} margin={{ left: -10, right: 8, top: 8 }}>
                <defs>
                  <linearGradient id="gv" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={INDIGO} stopOpacity={0.5} />
                    <stop offset="100%" stopColor={INDIGO} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="month" stroke={AXIS} fontSize={11} tickLine={false} />
                <YAxis stroke={AXIS} fontSize={11} tickLine={false} tickFormatter={(v) => formatCount(v)} />
                <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => formatCount(v)} />
                <Area type="monotone" dataKey="views" name={t("analytics.views")} stroke={INDIGO} fill="url(#gv)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Cluster performance */}
          <Card title={t("analytics.clusterPerf")}>
            {clusters.isLoading ? <Spinner /> : (clusters.data?.length ?? 0) === 0 ? (
              <Empty text={t("analytics.noClusters")} />
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(200, (clusters.data!.length) * 34)}>
                <BarChart data={clusters.data} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid stroke={GRID} horizontal={false} />
                  <XAxis type="number" stroke={AXIS} fontSize={11} tickLine={false} />
                  <YAxis type="category" dataKey="label" stroke={AXIS} fontSize={10} width={130} tickLine={false} />
                  <Tooltip contentStyle={TOOLTIP} formatter={(v: number, n) => n === "avg_weight" ? `${v}×` : formatCount(v)} />
                  <Bar dataKey="avg_weight" name={t("analytics.weight")} radius={[0, 5, 5, 0]}>
                    {clusters.data!.map((c) => (
                      <Cell key={c.id} fill={c.avg_weight >= 1 ? EMERALD : INDIGO} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="mt-2 text-xs text-zinc-600">{t("analytics.weightHint")}</p>
          </Card>

          {/* Benchmark */}
          <Card title={t("analytics.benchmark")}>
            {bench.isLoading ? <Spinner /> : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart
                  data={[
                    { name: "Medyca", views: bench.data?.medyca.avg_views ?? 0 },
                    { name: "Competitor", views: bench.data?.competitor.avg_views ?? 0 },
                  ]}
                  margin={{ left: -6, right: 8, top: 8 }}
                >
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="name" stroke={AXIS} fontSize={11} tickLine={false} />
                  <YAxis stroke={AXIS} fontSize={11} tickLine={false} tickFormatter={(v) => formatCount(v)} />
                  <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => formatCount(v)} />
                  <Bar dataKey="views" name={t("analytics.avgViews")} radius={[5, 5, 0, 0]}>
                    <Cell fill={EMERALD} />
                    <Cell fill={AMBER} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="mt-2 text-xs text-zinc-600">{t("analytics.benchmarkHint")}</p>
          </Card>
        </div>

        {/* Top content */}
        <Card title={t("analytics.topContent")}>
          {top.isLoading ? <Spinner /> : (
            <div className="flex flex-col divide-y divide-zinc-800">
              {top.data?.map((r, i) => (
                <a key={r.id} href={r.url} target="_blank" rel="noreferrer"
                  className="flex items-center gap-3 py-2.5 transition hover:bg-zinc-900/40">
                  <span className="w-5 text-center text-xs font-bold text-zinc-600">{i + 1}</span>
                  <div className="h-11 w-11 shrink-0 overflow-hidden rounded bg-zinc-800">
                    {r.thumbnail_file && <img src={mediaUrl(r.thumbnail_file) ?? ""} alt="" className="h-full w-full object-cover" />}
                  </div>
                  <span className="min-w-0 flex-1 truncate text-sm text-zinc-300">{r.title}</span>
                  <span className="shrink-0 text-xs text-zinc-500">▶ {formatCount(r.views)}</span>
                  <span className="shrink-0 rounded bg-emerald-600/20 px-2 py-0.5 text-xs font-semibold text-emerald-300">
                    {r.weight}×
                  </span>
                </a>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

const TOOLTIP = { background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 };

function Kpi({ label, value, text, fmt }: { label: string; value?: number; text?: string; fmt?: boolean }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 truncate text-2xl font-bold text-white">
        {text !== undefined ? text : value == null ? "—" : fmt ? formatCount(value) : value}
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h2>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-zinc-600">{text}</div>;
}
