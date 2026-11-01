import React, { useEffect, useState, useMemo } from "react";
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  BarChart3,
  Calendar,
  CheckCircle2,
  Clock,
  Layers,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
  Receipt,
  BookOpen,
  Search,
  ExternalLink,
  Youtube,
  LayoutDashboard,
  GitCompare,
  SlidersHorizontal,
  ChevronRight,
  Zap,
  Info,
  DollarSign,
  PieChart
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { cn, formatINR } from "@/lib/utils";

interface EquityPoint {
  date: string;
  equity: number;
  net_pnl: number;
  drawdown: number;
}

interface MonthlyRow {
  month: string;
  trades: number;
  wins: number;
  gross: number;
  charges: number;
  net: number;
}

interface TradeRecord {
  date: string;
  expiry: string;
  is_expiry: boolean;
  strategy: string;
  data_source: string;
  gross: number;
  charges: number;
  net: number;
  legs_traded: number;
}

interface StrategyBundle {
  key: string;
  title: string;
  subtitle: string;
  category: string;
  starting_capital: number;
  ending_capital: number;
  return_pct: number;
  calmar_ratio: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  gross_pnl: number;
  charges: number;
  net_pnl: number;
  max_dd: number;
  winning_months: number;
  total_months: number;
  year1_net: number;
  year1_dd: number;
  year1_wr: number;
  year2_net: number;
  year2_dd: number;
  year2_wr: number;
  monthly: MonthlyRow[];
  equity_curve: EquityPoint[];
  recent_trades: TradeRecord[];
}

interface PRSundarQuote {
  timestamp_sec: number;
  timestamp_str: string;
  score: number;
  quote: string;
}

interface PRSundarVideo {
  video_id: string;
  url: string;
  title: string;
  publish_date: string;
  duration: string;
  views: number;
  video_type?: string;
  categories: string[];
  word_count: number;
  quotes: PRSundarQuote[];
  transcript_preview: string;
}

interface PRSundarPlaybookSection {
  id: string;
  category: string;
  title: string;
  badge: string;
  summary: string;
  rules: string[];
  when_to_use: string;
}

interface PRSundarBrainPayload {
  generated_at: string;
  channel: {
    name: string;
    handle: string;
    url: string;
    total_videos_cataloged: number;
    total_transcripts_indexed: number;
    core_strategy_transcripts?: number;
    daily_report_transcripts?: number;
    total_spoken_words_indexed: number;
    total_views_cataloged: number;
  };
  synthesized_playbook: PRSundarPlaybookSection[];
  videos: PRSundarVideo[];
}

interface DtePhysicsRow {
  day: string;
  avg_straddle: number;
  pure_extrinsic_decay: number;
  avg_spot_move: number;
  fixed_straddle_decay: number;
  verdict: string;
}

interface DashboardPayload {
  generated_at: string;
  server_time: string;
  live_spot: number;
  period_start: string;
  period_end: string;
  total_trading_days: number;
  total_weekly_expiries: number;
  real_option_chain_weeks: number;
  spot_calibrated_weeks: number;
  lot_size: number;
  slippage_per_sl_order: number;
  dte_physics: DtePhysicsRow[];
  strategies: Record<string, StrategyBundle>;
}

// Cleaned up: only high-performing modern & PR Sundar strategies (no cluttered legacy baselines in main view)
const CORE_STRATEGIES = [
  "dynamic_pr_sundar",
  "combined",
  "pr_sundar",
  "institutional",
  "rolling_straddle",
  "oh_ol_wall"
] as const;

const STRATEGY_LABELS: Record<string, { name: string; tag: string; desc: string }> = {
  dynamic_pr_sundar: {
    name: "Full Dynamic PR Sundar (4-Engine)",
    tag: "92.3% Mo • Recommended",
    desc: "Weekly Strangle + Intraday Adaptive + 09:30 O=H/O=L Wall + 7% Collateral",
  },
  combined: {
    name: "Combined (#5 Weekly + #6 Intraday)",
    tag: "Flagship 88.5% Mo",
    desc: "Positional weekly strangle hedged with zero-overnight intraday adaptive straddles",
  },
  pr_sundar: {
    name: "PR Sundar Weekly Strangle (#5)",
    tag: "Positional Core",
    desc: "OTM ±100 Friday entry with untested-leg roll (50% decay trigger) & +44% SL",
  },
  institutional: {
    name: "Institutional Intraday Adaptive (#6)",
    tag: "Zero Overnight",
    desc: "Intraday regime-switching straddle/strangle with 1 re-entry on cost",
  },
  rolling_straddle: {
    name: "Institutional Rolling Straddle (#7)",
    tag: "Delta-Neutral",
    desc: "ATM Straddle re-centering whenever Nifty moves ±100 pts",
  },
  oh_ol_wall: {
    name: "09:30 Open=High/Low Wall Seller",
    tag: "Tactical Alpha",
    desc: "Sells opposite wall strike when 09:15-09:30 detects 81-84% directional trap",
  },
};

type ViewMode = "overview" | "comparison" | "brain" | "ledger";

export default function App() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [activeView, setActiveView] = useState<ViewMode>("overview");
  
  // Strategy selection
  const [selectedStrategy, setSelectedStrategy] = useState<string>("dynamic_pr_sundar");
  
  // Head-to-Head Compare selections
  const [compareA, setCompareA] = useState<string>("dynamic_pr_sundar");
  const [compareB, setCompareB] = useState<string>("pr_sundar");

  // Ledger Filter
  const [tradeFilter, setTradeFilter] = useState<"all" | "win" | "loss">("all");
  const [isRefreshing, setIsRefreshing] = useState(false);

  // PR Sundar Brain state
  const [brain, setBrain] = useState<PRSundarBrainPayload | null>(null);
  const [brainQuery, setBrainQuery] = useState<string>("");
  const [brainCategory, setBrainCategory] = useState<string>("all");
  const [brainResults, setBrainResults] = useState<PRSundarVideo[]>([]);
  const [isSearchingBrain, setIsSearchingBrain] = useState<boolean>(false);

  const fetchDashboard = async () => {
    try {
      const res = await fetch("/api/dashboard");
      const json = await res.json();
      setData(json);
    } catch (err) {
      console.error("Failed to fetch dashboard data:", err);
    }
  };

  const fetchBrain = async () => {
    try {
      const res = await fetch("/api/pr-sundar-brain");
      const json = await res.json();
      setBrain(json);
      if (json.videos) {
        setBrainResults(json.videos);
      }
    } catch (err) {
      console.error("Failed to fetch PR Sundar brain:", err);
    }
  };

  const handleBrainSearch = async (qOverride?: string, catOverride?: string) => {
    const q = qOverride !== undefined ? qOverride : brainQuery;
    const cat = catOverride !== undefined ? catOverride : brainCategory;
    setIsSearchingBrain(true);
    try {
      const params = new URLSearchParams({ q, category: cat, limit: "40" });
      const res = await fetch(`/api/pr-sundar-search?${params.toString()}`);
      const json = await res.json();
      if (json.results) {
        setBrainResults(json.results);
      }
    } catch (err) {
      console.error("Failed to search PR Sundar DB:", err);
    } finally {
      setIsSearchingBrain(false);
    }
  };

  const handleRecompute = async () => {
    setIsRefreshing(true);
    try {
      await fetch("/api/recompute", { method: "POST" });
      await fetchDashboard();
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
    fetchBrain();
    const timer = setInterval(fetchDashboard, 6000);
    return () => clearInterval(timer);
  }, []);

  const activeBundle: StrategyBundle | null = useMemo(() => {
    if (!data) return null;
    return data.strategies[selectedStrategy] || data.strategies.dynamic_pr_sundar || data.strategies.combined;
  }, [data, selectedStrategy]);

  const bundleA = useMemo(() => {
    if (!data) return null;
    return data.strategies[compareA] || data.strategies.dynamic_pr_sundar;
  }, [data, compareA]);

  const bundleB = useMemo(() => {
    if (!data) return null;
    return data.strategies[compareB] || data.strategies.pr_sundar;
  }, [data, compareB]);

  const filteredTrades = useMemo(() => {
    if (!activeBundle) return [];
    return activeBundle.recent_trades.filter((t) => {
      if (tradeFilter === "win") return t.net > 0;
      if (tradeFilter === "loss") return t.net <= 0;
      return true;
    });
  }, [activeBundle, tradeFilter]);

  if (!data || !activeBundle) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
        <Card className="max-w-md w-full text-center p-8 border-slate-200 shadow-sm bg-white">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 shadow-sm">
            <RefreshCw className="h-6 w-6 animate-spin" />
          </div>
          <CardTitle className="text-base font-semibold text-slate-900">Starting Antigravity Quant SaaS...</CardTitle>
          <CardDescription className="mt-1 text-slate-500">
            Streaming live Upstox spot, lot size physics & 2-year institutional telemetry
          </CardDescription>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 flex flex-col font-sans antialiased">
      {/* Top Navbar */}
      <header className="sticky top-0 z-40 w-full border-b border-slate-200/80 bg-white/95 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-tr from-blue-700 to-indigo-600 text-white shadow-md shadow-blue-500/20">
                <TrendingUp className="h-5 w-5" />
              </div>
              <div>
                <span className="text-sm font-bold tracking-tight text-slate-900">Antigravity Quant</span>
                <span className="ml-1.5 rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">PRO SaaS</span>
              </div>
            </div>

            {/* Live Ticker Badges */}
            <div className="hidden lg:flex items-center gap-2 border-l border-slate-200 pl-6 text-xs">
              <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 px-2.5 py-1 rounded-md">
                <span className="font-semibold text-slate-500 text-[11px]">NIFTY 50 SPOT:</span>
                <span className="font-mono font-bold text-slate-900">{data.live_spot.toLocaleString("en-IN", { minimumFractionDigits: 1 })}</span>
                <span className="relative flex h-2 w-2 ml-0.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
              </div>
              <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 px-2.5 py-1 rounded-md">
                <span className="font-semibold text-slate-500 text-[11px]">LOT SIZE:</span>
                <span className="font-mono font-bold text-slate-900">{data.lot_size} Qty</span>
              </div>
              <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 px-2.5 py-1 rounded-md">
                <span className="font-semibold text-slate-500 text-[11px]">PERIOD:</span>
                <span className="font-mono text-slate-700 text-[11px]">{data.period_start} → {data.period_end}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRecompute}
              disabled={isRefreshing}
              className="h-8 gap-1.5 border-slate-200 text-xs text-slate-700 hover:bg-slate-50"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
              {isRefreshing ? "Recomputing..." : "Sync Engine"}
            </Button>
            <div className="text-right hidden sm:block">
              <div className="text-[10px] font-mono text-slate-400">{data.server_time}</div>
            </div>
          </div>
        </div>
      </header>

      {/* Main SaaS Container with Modern Sidebar Layout */}
      <div className="mx-auto flex w-full max-w-7xl flex-1 px-4 sm:px-6 lg:px-8 py-6 gap-6">
        {/* Navigation Sidebar */}
        <aside className="w-56 shrink-0 hidden md:flex flex-col gap-1.5">
          <div className="px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            Navigation
          </div>
          <button
            onClick={() => setActiveView("overview")}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all",
              activeView === "overview"
                ? "bg-blue-600 text-white shadow-sm shadow-blue-600/20"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            )}
          >
            <LayoutDashboard className="h-4 w-4" />
            <span>Dashboard Overview</span>
          </button>
          
          <button
            onClick={() => setActiveView("comparison")}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all",
              activeView === "comparison"
                ? "bg-blue-600 text-white shadow-sm shadow-blue-600/20"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            )}
          >
            <GitCompare className="h-4 w-4" />
            <span>Head-to-Head Compare</span>
          </button>

          <button
            onClick={() => setActiveView("brain")}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all",
              activeView === "brain"
                ? "bg-blue-600 text-white shadow-sm shadow-blue-600/20"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            )}
          >
            <BookOpen className="h-4 w-4" />
            <span>P R Sundar Brain</span>
            <Badge variant="secondary" className="ml-auto text-[9px] px-1 py-0">3.7M w</Badge>
          </button>

          <button
            onClick={() => setActiveView("ledger")}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all",
              activeView === "ledger"
                ? "bg-blue-600 text-white shadow-sm shadow-blue-600/20"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            )}
          >
            <Activity className="h-4 w-4" />
            <span>Trade Audit Ledger</span>
          </button>

          <div className="mt-6 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            Quick Strategy Focus
          </div>
          <div className="space-y-1">
            {CORE_STRATEGIES.map((key) => {
              const info = STRATEGY_LABELS[key];
              const isSelected = selectedStrategy === key;
              return (
                <button
                  key={key}
                  onClick={() => {
                    setSelectedStrategy(key);
                    if (activeView !== "overview") setActiveView("overview");
                  }}
                  className={cn(
                    "w-full text-left rounded-lg p-2 text-xs transition-all border",
                    isSelected
                      ? "border-blue-300 bg-blue-50/70 text-blue-900 font-semibold"
                      : "border-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  )}
                >
                  <div className="truncate font-medium">{info?.name || key}</div>
                  <div className="text-[10px] text-slate-400">{info?.tag}</div>
                </button>
              );
            })}
          </div>

          <div className="mt-auto pt-6">
            <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 text-xs shadow-sm">
              <div className="flex items-center gap-1.5 font-bold text-slate-900 text-[11px]">
                <Zap className="h-3.5 w-3.5 text-amber-500 fill-amber-500" />
                Live Market Telemetry
              </div>
              <div className="mt-2 space-y-1 text-[11px] text-slate-500">
                <div className="flex justify-between">
                  <span>NSE Expiries:</span>
                  <span className="font-mono font-medium text-slate-700">{data.total_weekly_expiries} wks</span>
                </div>
                <div className="flex justify-between">
                  <span>Trading Days:</span>
                  <span className="font-mono font-medium text-slate-700">{data.total_trading_days} days</span>
                </div>
                <div className="flex justify-between">
                  <span>Brokerage / Lot:</span>
                  <span className="font-mono font-medium text-slate-700">₹20 flat</span>
                </div>
              </div>
            </div>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 min-w-0">
          {/* Mobile Tab Bar */}
          <div className="flex md:hidden overflow-x-auto gap-2 pb-3 mb-4 border-b border-slate-200">
            <Button
              variant={activeView === "overview" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveView("overview")}
              className="text-xs shrink-0"
            >
              Overview
            </Button>
            <Button
              variant={activeView === "comparison" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveView("comparison")}
              className="text-xs shrink-0"
            >
              Compare
            </Button>
            <Button
              variant={activeView === "brain" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveView("brain")}
              className="text-xs shrink-0"
            >
              PR Sundar Brain
            </Button>
            <Button
              variant={activeView === "ledger" ? "default" : "outline"}
              size="sm"
              onClick={() => setActiveView("ledger")}
              className="text-xs shrink-0"
            >
              Ledger
            </Button>
          </div>

          {/* VIEW 1: OVERVIEW DASHBOARD */}
          {activeView === "overview" && (
            <div className="space-y-6 quant-containment-section">
              {/* Header Hero Card */}
              <div className="rounded-2xl border border-slate-200/90 bg-white p-6 shadow-sm">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-blue-600 font-mono">
                        Active Strategy Telemetry
                      </span>
                      <Badge variant="outline" className="text-[10px]">
                        {STRATEGY_LABELS[selectedStrategy]?.tag || "Verified System"}
                      </Badge>
                    </div>
                    <h2 className="text-xl font-bold tracking-tight text-slate-900 mt-1">
                      {activeBundle.title}
                    </h2>
                    <p className="text-xs text-slate-500 mt-0.5 max-w-2xl">
                      {activeBundle.subtitle}
                    </p>
                  </div>

                  {/* Strategy Selector Pillbox */}
                  <div className="flex flex-wrap items-center gap-1.5 bg-slate-100/80 p-1 rounded-xl border border-slate-200/60">
                    {CORE_STRATEGIES.map((key) => {
                      const isSel = selectedStrategy === key;
                      return (
                        <button
                          key={key}
                          onClick={() => setSelectedStrategy(key)}
                          className={cn(
                            "px-2.5 py-1 text-xs font-semibold rounded-lg transition-all",
                            isSel
                              ? "bg-white text-slate-900 shadow-sm"
                              : "text-slate-600 hover:text-slate-900"
                          )}
                        >
                          {key === "dynamic_pr_sundar"
                            ? "Dynamic Flagship"
                            : key === "combined"
                            ? "Combined"
                            : key === "pr_sundar"
                            ? "PR Sundar #5"
                            : key === "institutional"
                            ? "Intraday #6"
                            : key === "rolling_straddle"
                            ? "Rolling #7"
                            : "09:30 Wall"}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* 4 Clean Metric Cards */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6">
                  <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      2-Year Net In-Pocket
                    </span>
                    <div
                      className={cn(
                        "mt-1.5 font-mono text-2xl font-bold",
                        activeBundle.net_pnl >= 0 ? "text-emerald-600" : "text-rose-600"
                      )}
                    >
                      {formatINR(activeBundle.net_pnl, true)}
                    </div>
                    <div className="mt-1 flex items-center gap-1 text-[11px] font-mono font-medium text-slate-500">
                      <span>ROI:</span>
                      <strong className="text-slate-700">{activeBundle.return_pct}%</strong>
                      <span className="text-slate-400">({activeBundle.total_trades} trades)</span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Monthly Win Consistency
                    </span>
                    <div className="mt-1.5 font-mono text-2xl font-bold text-slate-900">
                      {activeBundle.winning_months} / {activeBundle.total_months} Mo
                    </div>
                    <div className="mt-1 flex items-center gap-1 text-[11px] font-mono font-medium text-emerald-600">
                      <span>Win Rate:</span>
                      <strong>{Math.round((activeBundle.winning_months / activeBundle.total_months) * 100)}% Months Positive</strong>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Max Drawdown
                    </span>
                    <div className="mt-1.5 font-mono text-2xl font-bold text-amber-700">
                      {formatINR(activeBundle.max_dd)}
                    </div>
                    <div className="mt-1 flex items-center gap-1 text-[11px] font-mono font-medium text-slate-500">
                      <span>Calmar Ratio:</span>
                      <strong className="text-slate-700">{activeBundle.calmar_ratio}x</strong>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-4">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                      Gross P&L vs Taxes
                    </span>
                    <div className="mt-1.5 font-mono text-2xl font-bold text-slate-800">
                      {formatINR(activeBundle.gross_pnl, true)}
                    </div>
                    <div className="mt-1 flex items-center gap-1 text-[11px] font-mono font-medium text-rose-600">
                      <span>Fees & STT:</span>
                      <strong>-{formatINR(activeBundle.charges)}</strong>
                    </div>
                  </div>
                </div>
              </div>

              {/* Equity Curve & Regime Breakout */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <Card className="lg:col-span-2 border-slate-200/90 shadow-sm">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <div>
                        <CardTitle className="text-sm font-bold text-slate-900">
                          2-Year Equity Curve ({data.period_start} → {data.period_end})
                        </CardTitle>
                        <CardDescription className="text-xs text-slate-500">
                          Net portfolio growth after all Zerodha brokerage, STT, and exchange taxes (1 Lot = 65 Qty)
                        </CardDescription>
                      </div>
                      <Badge variant="outline" className="font-mono text-xs">
                        Cap: {formatINR(activeBundle.ending_capital)}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-2">
                    <EquityCurveSVG
                      curve={activeBundle.equity_curve}
                      startingCapital={activeBundle.starting_capital}
                    />
                  </CardContent>
                </Card>

                {/* 2-Year Yearly Breakdown */}
                <Card className="border-slate-200/90 shadow-sm flex flex-col justify-between">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-bold text-slate-900">
                      Regime Stress Test (Year 1 vs Year 2)
                    </CardTitle>
                    <CardDescription className="text-xs text-slate-500">
                      Performance split before and after NSE Thursday → Tuesday expiry shift
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-3.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-700">Year 1 (Oct 2024 – Oct 2025)</span>
                        <Badge variant={activeBundle.year1_net >= 0 ? "success" : "destructive"} className="text-[10px]">
                          WR: {activeBundle.year1_wr}%
                        </Badge>
                      </div>
                      <div className="mt-2 flex items-baseline justify-between">
                        <span
                          className={cn(
                            "font-mono text-lg font-bold",
                            activeBundle.year1_net >= 0 ? "text-emerald-600" : "text-rose-600"
                          )}
                        >
                          {formatINR(activeBundle.year1_net, true)}
                        </span>
                        <span className="text-[11px] text-slate-500">
                          Max DD: <strong className="font-mono text-slate-700">{formatINR(activeBundle.year1_dd)}</strong>
                        </span>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-3.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-700">Year 2 (Nov 2025 – Oct 2026)</span>
                        <Badge variant={activeBundle.year2_net >= 0 ? "success" : "destructive"} className="text-[10px]">
                          WR: {activeBundle.year2_wr}%
                        </Badge>
                      </div>
                      <div className="mt-2 flex items-baseline justify-between">
                        <span
                          className={cn(
                            "font-mono text-lg font-bold",
                            activeBundle.year2_net >= 0 ? "text-emerald-600" : "text-rose-600"
                          )}
                        >
                          {formatINR(activeBundle.year2_net, true)}
                        </span>
                        <span className="text-[11px] text-slate-500">
                          Max DD: <strong className="font-mono text-slate-700">{formatINR(activeBundle.year2_dd)}</strong>
                        </span>
                      </div>
                    </div>

                    <div className="rounded-lg bg-blue-50/60 border border-blue-100 p-3 text-[11px] text-blue-900 leading-relaxed">
                      <strong>Expiry Adaptation:</strong> In Aug 2025, NSE shifted Nifty expiry from Thursday to Tuesday. The engine dynamically auto-switched to DTE ≤ 4 calendar days with zero friction.
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Month-by-Month Calendar Heatmap */}
              <Card className="border-slate-200/90 shadow-sm">
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <div>
                    <CardTitle className="text-sm font-bold text-slate-900">
                      Month-by-Month Net P&L Matrix ({activeBundle.title})
                    </CardTitle>
                    <CardDescription className="text-xs text-slate-500">
                      Verified {activeBundle.winning_months} green months out of {activeBundle.total_months} calendar months
                    </CardDescription>
                  </div>
                  <Badge variant="outline" className="text-xs font-mono font-semibold">
                    {Math.round((activeBundle.winning_months / activeBundle.total_months) * 100)}% Accuracy
                  </Badge>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2.5">
                    {activeBundle.monthly.map((m) => {
                      const isPositive = m.net > 0;
                      return (
                        <div
                          key={m.month}
                          className={cn(
                            "rounded-xl border p-3 transition-all",
                            isPositive
                              ? "border-emerald-200/80 bg-emerald-50/30 hover:bg-emerald-50/60"
                              : "border-rose-200/80 bg-rose-50/30 hover:bg-rose-50/60"
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-xs font-bold text-slate-700">{m.month}</span>
                            <span
                              className={cn(
                                "text-[10px] font-mono font-semibold",
                                isPositive ? "text-emerald-700" : "text-rose-700"
                              )}
                            >
                              {m.wins}/{m.trades}W
                            </span>
                          </div>
                          <div
                            className={cn(
                              "mt-1.5 font-mono text-sm font-bold",
                              isPositive ? "text-emerald-700" : "text-rose-700"
                            )}
                          >
                            {formatINR(m.net, true)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* VIEW 2: HEAD-TO-HEAD STRATEGY COMPARISON */}
          {activeView === "comparison" && (
            <div className="space-y-6 quant-containment-section">
              {/* Compare Selector Bar */}
              <Card className="border-slate-200/90 shadow-sm bg-white">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base font-bold text-slate-900 flex items-center gap-2">
                    <GitCompare className="h-5 w-5 text-blue-600" />
                    Head-to-Head Strategy Comparison Tool
                  </CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    Pick any two strategies to directly benchmark their risk, returns, drawdown, and win rates side-by-side
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-semibold text-slate-600 mb-1.5 block">
                        Strategy A (Baseline):
                      </label>
                      <select
                        value={compareA}
                        onChange={(e) => setCompareA(e.target.value)}
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-900 focus:border-blue-600 focus:outline-none"
                      >
                        {CORE_STRATEGIES.map((k) => (
                          <option key={k} value={k}>
                            {STRATEGY_LABELS[k]?.name || k}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-slate-600 mb-1.5 block">
                        Strategy B (Challenger):
                      </label>
                      <select
                        value={compareB}
                        onChange={(e) => setCompareB(e.target.value)}
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-900 focus:border-blue-600 focus:outline-none"
                      >
                        {CORE_STRATEGIES.map((k) => (
                          <option key={k} value={k}>
                            {STRATEGY_LABELS[k]?.name || k}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Side-by-Side Comparison Cards */}
              {bundleA && bundleB && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Strategy A Card */}
                  <Card className="border-blue-200/90 bg-gradient-to-b from-blue-50/30 to-white shadow-sm">
                    <CardHeader className="pb-3 border-b border-slate-100">
                      <Badge variant="info" className="w-fit text-[10px]">
                        Strategy A
                      </Badge>
                      <CardTitle className="text-base font-bold text-slate-900 mt-1">
                        {bundleA.title}
                      </CardTitle>
                      <CardDescription className="text-xs text-slate-500">
                        {bundleA.subtitle}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="pt-4 space-y-3.5 text-xs">
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">2-Year Net Profit:</span>
                        <span className="font-mono text-base font-bold text-emerald-600">
                          {formatINR(bundleA.net_pnl, true)}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Win Rate:</span>
                        <span className="font-mono font-semibold text-slate-900">
                          {bundleA.win_rate}% ({bundleA.wins}W / {bundleA.losses}L)
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Winning Months:</span>
                        <span className="font-mono font-semibold text-slate-900">
                          {bundleA.winning_months} / {bundleA.total_months} Mo ({Math.round((bundleA.winning_months / bundleA.total_months) * 100)}%)
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Max Drawdown:</span>
                        <span className="font-mono font-semibold text-amber-700">
                          {formatINR(bundleA.max_dd)}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Calmar (Net / Max DD):</span>
                        <span className="font-mono font-semibold text-blue-700">
                          {bundleA.calmar_ratio}x
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1">
                        <span className="text-slate-500">Taxes & Brokerage:</span>
                        <span className="font-mono font-medium text-rose-600">
                          -{formatINR(bundleA.charges)}
                        </span>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Strategy B Card */}
                  <Card className="border-indigo-200/90 bg-gradient-to-b from-indigo-50/30 to-white shadow-sm">
                    <CardHeader className="pb-3 border-b border-slate-100">
                      <Badge variant="secondary" className="w-fit text-[10px] bg-indigo-100 text-indigo-800">
                        Strategy B
                      </Badge>
                      <CardTitle className="text-base font-bold text-slate-900 mt-1">
                        {bundleB.title}
                      </CardTitle>
                      <CardDescription className="text-xs text-slate-500">
                        {bundleB.subtitle}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="pt-4 space-y-3.5 text-xs">
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">2-Year Net Profit:</span>
                        <span className="font-mono text-base font-bold text-emerald-600">
                          {formatINR(bundleB.net_pnl, true)}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Win Rate:</span>
                        <span className="font-mono font-semibold text-slate-900">
                          {bundleB.win_rate}% ({bundleB.wins}W / {bundleB.losses}L)
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Winning Months:</span>
                        <span className="font-mono font-semibold text-slate-900">
                          {bundleB.winning_months} / {bundleB.total_months} Mo ({Math.round((bundleB.winning_months / bundleB.total_months) * 100)}%)
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Max Drawdown:</span>
                        <span className="font-mono font-semibold text-amber-700">
                          {formatINR(bundleB.max_dd)}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-100">
                        <span className="text-slate-500">Calmar (Net / Max DD):</span>
                        <span className="font-mono font-semibold text-blue-700">
                          {bundleB.calmar_ratio}x
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1">
                        <span className="text-slate-500">Taxes & Brokerage:</span>
                        <span className="font-mono font-medium text-rose-600">
                          -{formatINR(bundleB.charges)}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}

              {/* Master Comparison Table of all clean strategies */}
              <Card className="border-slate-200/90 shadow-sm">
                <CardHeader>
                  <CardTitle className="text-sm font-bold text-slate-900">
                    Full 2-Year Multi-Strategy League Table
                  </CardTitle>
                  <CardDescription className="text-xs text-slate-500">
                    Real 1-minute Upstox backtest (Oct 2024 – Oct 2026 | 1 Lot = 65 Qty)
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="quant-table-region rounded-xl border border-slate-200">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Strategy</TableHead>
                          <TableHead>Trades</TableHead>
                          <TableHead>Win Rate</TableHead>
                          <TableHead>Year 1 Net</TableHead>
                          <TableHead>Year 2 Net</TableHead>
                          <TableHead>Total Net P&L</TableHead>
                          <TableHead>Max DD</TableHead>
                          <TableHead>Winning Months</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {CORE_STRATEGIES.map((key) => {
                          const b = data.strategies[key];
                          if (!b) return null;
                          const isSel = selectedStrategy === key;
                          return (
                            <TableRow
                              key={key}
                              onClick={() => setSelectedStrategy(key)}
                              className={cn(
                                "cursor-pointer transition-colors",
                                isSel && "bg-blue-50/70"
                              )}
                            >
                              <th scope="row" className="px-4 py-3 text-left font-semibold text-slate-900 border-b border-slate-100">
                                <div>{b.title}</div>
                                <div className="text-[10px] text-slate-400 font-normal">{b.category}</div>
                              </th>
                              <TableCell className="font-mono">{b.total_trades}</TableCell>
                              <TableCell className="font-mono font-semibold">{b.win_rate}%</TableCell>
                              <TableCell className={cn("font-mono font-semibold", b.year1_net >= 0 ? "text-emerald-600" : "text-rose-600")}>
                                {formatINR(b.year1_net, true)}
                              </TableCell>
                              <TableCell className={cn("font-mono font-semibold", b.year2_net >= 0 ? "text-emerald-600" : "text-rose-600")}>
                                {formatINR(b.year2_net, true)}
                              </TableCell>
                              <TableCell className={cn("font-mono font-bold text-sm", b.net_pnl >= 0 ? "text-emerald-600" : "text-rose-600")}>
                                {formatINR(b.net_pnl, true)}
                              </TableCell>
                              <TableCell className="font-mono text-amber-700">{formatINR(b.max_dd)}</TableCell>
                              <TableCell>
                                <Badge variant={b.winning_months >= 20 ? "success" : "secondary"} className="text-[10px]">
                                  {b.winning_months} / {b.total_months} Mo
                                </Badge>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* VIEW 3: PR SUNDAR BRAIN & PLAYBOOK */}
          {activeView === "brain" && (
            <div className="space-y-6 quant-containment-section">
              {brain && (
                <>
                  <div className="rounded-2xl border border-blue-200/90 bg-gradient-to-r from-blue-50 via-white to-indigo-50/50 p-6 shadow-sm">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <Badge variant="info" className="font-mono text-[10px]">
                            {brain.channel.handle} • Complete Channel Index
                          </Badge>
                          <Badge variant="success" className="font-mono text-[10px]">
                            {brain.channel.total_spoken_words_indexed.toLocaleString("en-IN")} Spoken Words
                          </Badge>
                        </div>
                        <h2 className="text-xl font-bold tracking-tight text-slate-900 mt-2">
                          P R Sundar Strategy Brain ({brain.channel.total_videos_cataloged.toLocaleString("en-IN")} Videos)
                        </h2>
                        <p className="text-xs text-slate-500 mt-1 max-w-2xl">
                          Full start-to-finish transcripts mined across {brain.channel.total_transcripts_indexed.toLocaleString("en-IN")} videos into local SQLite FTS5 database.
                        </p>
                      </div>

                      <a
                        href={brain.channel.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 w-fit shrink-0"
                      >
                        <Youtube className="h-4 w-4 text-rose-600" />
                        Channel on YouTube
                        <ExternalLink className="h-3 w-3 text-slate-400" />
                      </a>
                    </div>
                  </div>

                  {/* 5-Part Synthesized Playbook */}
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 px-1">
                      Synthesized 5-Pillar Trading Playbook (Mined from 3.73 Million Spoken Words)
                    </h3>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                      {brain.synthesized_playbook.map((sec) => (
                        <Card key={sec.id} className="border-slate-200/90 shadow-sm">
                          <CardHeader className="pb-2">
                            <div className="flex items-center justify-between gap-2">
                              <Badge variant="secondary" className="text-[10px]">
                                {sec.category}
                              </Badge>
                              <Badge variant="info" className="text-[10px]">
                                {sec.badge}
                              </Badge>
                            </div>
                            <CardTitle className="mt-1 text-sm font-bold text-slate-900">
                              {sec.title}
                            </CardTitle>
                            <CardDescription className="text-xs leading-relaxed text-slate-600">
                              {sec.summary}
                            </CardDescription>
                          </CardHeader>
                          <CardContent className="space-y-2 text-xs text-slate-700">
                            <ul className="list-disc pl-4 space-y-1 text-[11px] leading-relaxed">
                              {sec.rules.map((r, i) => (
                                <li key={i}>{r}</li>
                              ))}
                            </ul>
                            <div className="rounded-lg bg-slate-50 border border-slate-100 p-2 text-[11px] font-medium text-slate-700">
                              <strong>Deployment condition:</strong> {sec.when_to_use}
                            </div>
                          </CardContent>
                        </Card>
                      ))}
                    </div>
                  </div>

                  {/* Full-Text Video Search */}
                  <Card className="border-slate-200/90 shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-bold text-slate-900 flex items-center gap-2">
                        <Search className="h-4 w-4 text-blue-600" />
                        Search Across 2,872 Full Transcripts
                      </CardTitle>
                      <CardDescription className="text-xs text-slate-500">
                        Search any rule or keyword (e.g. &ldquo;firefighting&rdquo;, &ldquo;ratio spread&rdquo;, &ldquo;low vix&rdquo;, &ldquo;1.3 crore&rdquo;, &ldquo;open high&rdquo;)
                      </CardDescription>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <div className="relative flex-1 min-w-[240px]">
                          <input
                            type="text"
                            value={brainQuery}
                            onChange={(e) => setBrainQuery(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleBrainSearch();
                            }}
                            placeholder="Type to search exact spoken words..."
                            className="w-full rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus:border-blue-600 focus:outline-none"
                          />
                        </div>
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => handleBrainSearch()}
                          disabled={isSearchingBrain}
                          className="text-xs"
                        >
                          <Search className="h-3.5 w-3.5" />
                          {isSearchingBrain ? "Searching..." : "Search"}
                        </Button>
                      </div>

                      {/* Filter pills */}
                      <div className="mt-2.5 flex flex-wrap gap-1.5">
                        {[
                          ["all", "All Topics"],
                          ["option_selling", "Option Selling"],
                          ["firefighting", "Firefighting"],
                          ["option_buying", "Option Buying"],
                          ["common_sense", "Common Sense & VIX"],
                          ["margin_hedging", "Collateral & Margin"],
                          ["expiry_day", "Expiry Day"],
                        ].map(([catKey, label]) => (
                          <button
                            key={catKey}
                            onClick={() => {
                              setBrainCategory(catKey);
                              handleBrainSearch(brainQuery, catKey);
                            }}
                            className={cn(
                              "rounded-lg px-2.5 py-1 text-[11px] font-medium transition-all border",
                              brainCategory === catKey
                                ? "border-blue-300 bg-blue-50 text-blue-900 font-semibold"
                                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                            )}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </CardHeader>

                    <CardContent>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                        {brainResults.slice(0, 16).map((v) => (
                          <div
                            key={v.video_id}
                            className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm hover:border-blue-300 transition-all flex flex-col justify-between"
                          >
                            <div>
                              <div className="flex items-start justify-between gap-2">
                                <a
                                  href={v.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-xs font-bold text-slate-900 hover:text-blue-600 flex items-center gap-1 leading-snug"
                                >
                                  <span>{v.title}</span>
                                  <ExternalLink className="h-3 w-3 shrink-0 text-slate-400" />
                                </a>
                                <Badge variant="secondary" className="shrink-0 font-mono text-[10px]">
                                  {(v.views || 0).toLocaleString("en-IN")} views
                                </Badge>
                              </div>

                              <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                                {v.duration && <span>⏱ {v.duration}</span>}
                                {v.word_count > 0 && <span>• 📝 {v.word_count.toLocaleString("en-IN")} words</span>}
                              </div>

                              {v.quotes && v.quotes.length > 0 && (
                                <div className="mt-2.5 rounded-lg border border-blue-100 bg-blue-50/50 p-2 text-[11px] text-slate-700">
                                  <div className="flex items-center justify-between font-mono text-[10px] font-bold text-blue-700">
                                    <span>Key Spoken Quote @{v.quotes[0].timestamp_str}</span>
                                    <a
                                      href={`${v.url}&t=${v.quotes[0].timestamp_sec}s`}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="underline hover:text-blue-900"
                                    >
                                      Jump to video →
                                    </a>
                                  </div>
                                  <p className="mt-1 italic leading-relaxed text-slate-700">
                                    &ldquo;{v.quotes[0].quote}&rdquo;
                                  </p>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </>
              )}
            </div>
          )}

          {/* VIEW 4: TRADE AUDIT LEDGER */}
          {activeView === "ledger" && (
            <div className="space-y-4 quant-containment-section">
              <Card className="border-slate-200/90 shadow-sm">
                <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3">
                  <div>
                    <CardTitle className="text-sm font-bold text-slate-900">
                      Verified Trade Audit Journal — {activeBundle.title}
                    </CardTitle>
                    <CardDescription className="text-xs text-slate-500">
                      Showing latest {filteredTrades.length} executed positions with real NSE slippage & Zerodha charges
                    </CardDescription>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <Button
                      variant={tradeFilter === "all" ? "default" : "outline"}
                      size="sm"
                      onClick={() => setTradeFilter("all")}
                      className="text-xs h-7"
                    >
                      All ({activeBundle.recent_trades.length})
                    </Button>
                    <Button
                      variant={tradeFilter === "win" ? "primary" : "outline"}
                      size="sm"
                      onClick={() => setTradeFilter("win")}
                      className="text-xs h-7"
                    >
                      Wins Only
                    </Button>
                    <Button
                      variant={tradeFilter === "loss" ? "outline" : "outline"}
                      size="sm"
                      onClick={() => setTradeFilter("loss")}
                      className="text-xs h-7"
                    >
                      Losses Only
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="quant-table-region rounded-xl border border-slate-200">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Trade Date</TableHead>
                          <TableHead>Strategy</TableHead>
                          <TableHead>Expiry</TableHead>
                          <TableHead>Gross P&L</TableHead>
                          <TableHead>Brokerage & Tax</TableHead>
                          <TableHead>Net In-Pocket</TableHead>
                          <TableHead>Result</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filteredTrades.map((t, idx) => {
                          const isWin = t.net > 0;
                          return (
                            <TableRow key={`${t.date}-${idx}`}>
                              <th scope="row" className="px-4 py-3 font-mono font-semibold text-slate-900 border-b border-slate-100">
                                {t.date}
                                {t.is_expiry && (
                                  <span className="ml-1.5 rounded bg-amber-100 px-1 py-0.5 text-[9px] font-sans font-semibold text-amber-800">
                                    EXPIRY
                                  </span>
                                )}
                              </th>
                              <TableCell className="text-slate-700 font-medium text-xs">{t.strategy}</TableCell>
                              <TableCell className="font-mono text-slate-500 text-xs">{t.expiry}</TableCell>
                              <TableCell
                                className={cn(
                                  "font-mono text-xs font-medium",
                                  t.gross >= 0 ? "text-emerald-600" : "text-rose-600"
                                )}
                              >
                                {formatINR(t.gross, true)}
                              </TableCell>
                              <TableCell className="font-mono text-slate-400 text-xs">
                                -{formatINR(t.charges)}
                              </TableCell>
                              <TableCell
                                className={cn(
                                  "font-mono text-xs font-bold",
                                  isWin ? "text-emerald-600" : "text-rose-600"
                                )}
                              >
                                {formatINR(t.net, true)}
                              </TableCell>
                              <TableCell>
                                <Badge variant={isWin ? "success" : "destructive"} className="text-[10px]">
                                  {isWin ? (
                                    <span className="flex items-center gap-1">
                                      <ArrowUpRight className="h-3 w-3" /> PROFIT
                                    </span>
                                  ) : (
                                    <span className="flex items-center gap-1">
                                      <ArrowDownRight className="h-3 w-3" /> LOSS
                                    </span>
                                  )}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function EquityCurveSVG({
  curve,
  startingCapital,
}: {
  curve: EquityPoint[];
  startingCapital: number;
}) {
  if (!curve || curve.length < 2) return null;

  const W = 780;
  const H = 240;
  const padX = 48;
  const padY = 20;

  const values = [startingCapital, ...curve.map((c) => c.equity)];
  const minVal = Math.min(...values) * 0.985;
  const maxVal = Math.max(...values) * 1.015;
  const range = Math.max(1, maxVal - minVal);

  const coords = values.map((val, idx) => {
    const x = padX + (idx / (values.length - 1)) * (W - padX - 20);
    const y = H - padY - ((val - minVal) / range) * (H - padY * 2);
    return { x, y, val };
  });

  const baselineY = H - padY - ((startingCapital - minVal) / range) * (H - padY * 2);
  const isOverallPositive = values[values.length - 1] >= startingCapital;
  const strokeColor = isOverallPositive ? "#059669" : "#e11d48";

  const pathD = coords
    .map((pt, i) => `${i === 0 ? "M" : "L"} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`)
    .join(" ");
  const areaD = `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${H - padY} L ${coords[0].x.toFixed(1)} ${H - padY} Z`;

  return (
    <div className="w-full overflow-hidden">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-56 overflow-visible">
        <defs>
          <linearGradient id="cleanEquityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.18" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0.00" />
          </linearGradient>
        </defs>

        {/* Horizontal grid lines */}
        {[0, 0.33, 0.66, 1].map((frac, idx) => {
          const y = padY + frac * (H - padY * 2);
          const labelVal = maxVal - frac * range;
          return (
            <g key={idx}>
              <line
                x1={padX}
                y1={y}
                x2={W - 20}
                y2={y}
                stroke="#f1f5f9"
                strokeDasharray="3 3"
              />
              <text
                x={4}
                y={y + 4}
                className="fill-slate-400 font-mono text-[10px]"
              >
                ₹{Math.round(labelVal / 1000)}k
              </text>
            </g>
          );
        })}

        {/* Starting capital baseline */}
        <line
          x1={padX}
          y1={baselineY}
          x2={W - 20}
          y2={baselineY}
          stroke="#cbd5e1"
          strokeWidth="1"
          strokeDasharray="4 4"
        />

        {/* Equity Area & Line */}
        <path d={areaD} fill="url(#cleanEquityGrad)" />
        <path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Latest Point Dot */}
        <circle
          cx={coords[coords.length - 1].x}
          cy={coords[coords.length - 1].y}
          r="4.5"
          fill={strokeColor}
          stroke="#ffffff"
          strokeWidth="2"
        />
      </svg>
      <div className="mt-1 flex items-center justify-between px-4 text-[10px] font-mono text-slate-400">
        <span>Start: {curve[0]?.date}</span>
        <span>Mid: {curve[Math.floor(curve.length / 2)]?.date}</span>
        <span>Latest: {curve[curve.length - 1]?.date}</span>
      </div>
    </div>
  );
}
