"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsUpDown,
  Download,
  RotateCcw,
  Search,
  ShieldAlert,
} from "lucide-react";
import clsx from "clsx";
import PageShell from "@/components/layout/PageShell";
import GlassCard from "@/components/ui/GlassCard";
import CategoryChip from "@/components/ui/CategoryChip";
import StatusChip from "@/components/ui/StatusChip";
import InvestigationDrawer from "@/components/features/InvestigationDrawer";
import { THREAT_EVENTS, SEVERITY_HEX } from "@/lib/mock-data";
import {
  formatClockUTC,
  formatDayISOUTC,
  formatPercent,
  riskTextClass,
} from "@/lib/format";
import type {
  AlertWorkflowStatus,
  AttackKind,
  SeverityLevel,
  ThreatEvent,
} from "@/types";

/* -------------------------------------------------------------------------- */
/*  Filter & sort vocabulary                                                   */
/* -------------------------------------------------------------------------- */

type CategoryFilter = "all" | AttackKind;
type SeverityFilter = "all" | SeverityLevel;
type StatusFilter = "all" | AlertWorkflowStatus;

interface Filters {
  category: CategoryFilter;
  severity: SeverityFilter;
  status: StatusFilter;
  from: string;
  to: string;
  query: string;
}

const INITIAL_FILTERS: Filters = {
  category: "all",
  severity: "all",
  status: "all",
  from: "",
  to: "",
  query: "",
};

type ThreatSortKey =
  | "timestamp"
  | "source"
  | "destination"
  | "category"
  | "attackType"
  | "confidence"
  | "riskScore"
  | "status";

const COLUMNS: Array<{ key: ThreatSortKey; label: string; align?: "right" }> = [
  { key: "timestamp", label: "Timestamp" },
  { key: "source", label: "Source" },
  { key: "destination", label: "Destination" },
  { key: "category", label: "Category" },
  { key: "attackType", label: "Attack Type" },
  { key: "confidence", label: "Confidence" },
  { key: "riskScore", label: "Risk" },
  { key: "status", label: "Status" },
];

const PAGE_SIZES = [10, 25, 50] as const;

/* -------------------------------------------------------------------------- */
/*  Page                                                                       */
/* -------------------------------------------------------------------------- */

export default function ThreatsPage() {
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [sortKey, setSortKey] = useState<ThreatSortKey>("timestamp");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(25);
  const [selected, setSelected] = useState<ThreatEvent | null>(null);

  const updateFilters = (patch: Partial<Filters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };

  const filtered = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    return THREAT_EVENTS.filter((event) => {
      if (filters.category !== "all" && event.category !== filters.category) return false;
      if (filters.severity !== "all" && event.severity !== filters.severity) return false;
      if (filters.status !== "all" && event.status !== filters.status) return false;
      const day = formatDayISOUTC(event.timestamp);
      if (filters.from && day < filters.from) return false;
      if (filters.to && day > filters.to) return false;
      if (
        query &&
        ![event.id, event.source, event.destination, event.attackType, event.category]
          .join(" ")
          .toLowerCase()
          .includes(query)
      ) {
        return false;
      }
      return true;
    });
  }, [filters]);

  const sorted = useMemo(() => {
    const rows = [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return av - bv;
      return String(av).localeCompare(String(bv));
    });
    return sortDir === "desc" ? rows.reverse() : rows;
  }, [filtered, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const paged = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);
  const rangeStart = sorted.length === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const rangeEnd = Math.min(sorted.length, safePage * pageSize);

  const toggleSort = (key: ThreatSortKey) => {
    if (key === sortKey) {
      setSortDir((dir) => (dir === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(1);
  };

  const resetFilters = () => {
    setFilters(INITIAL_FILTERS);
    setPage(1);
  };

  /* Real client-side CSV export of the current (filtered + sorted) view. */
  const exportCsv = () => {
    const header = [
      "Event ID",
      "Timestamp (UTC)",
      "Source",
      "Source IP",
      "Destination",
      "Destination IP",
      "Protocol",
      "Category",
      "Attack Type",
      "Confidence",
      "Risk Score",
      "Severity",
      "Status",
    ];
    const lines = sorted.map((event) =>
      [
        event.id,
        event.timestamp,
        event.source,
        event.sourceIp,
        event.destination,
        event.destinationIp,
        event.protocol,
        event.category,
        event.attackType,
        formatPercent(event.confidence * 100),
        event.riskScore,
        event.severity,
        event.status,
      ].join(","),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `cybershield-threats-${formatDayISOUTC(
      new Date().toISOString(),
    )}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const activeFilterCount =
    (filters.category !== "all" ? 1 : 0) +
    (filters.severity !== "all" ? 1 : 0) +
    (filters.status !== "all" ? 1 : 0) +
    (filters.from ? 1 : 0) +
    (filters.to ? 1 : 0) +
    (filters.query ? 1 : 0);

  return (
    <PageShell
      title="Threat Detection"
      description="Signature and ML-based detections across the monitored estate, scored and ranked by severity."
      icon={ShieldAlert}
      moduleIndex="03 / 10"
    >
      <div className="space-y-5">
        {/* ---------------------------------------------------------------- */}
        {/* Filter bar                                                        */}
        {/* ---------------------------------------------------------------- */}
        <GlassCard className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <FilterSelect
              label="Attack Type"
              value={filters.category}
              onChange={(value) => updateFilters({ category: value as CategoryFilter })}
              options={[
                { value: "all", label: "All types" },
                { value: "dos", label: "DoS" },
                { value: "probe", label: "Probe" },
                { value: "r2l", label: "R2L" },
                { value: "u2r", label: "U2R" },
              ]}
            />
            <FilterSelect
              label="Severity"
              value={filters.severity}
              onChange={(value) => updateFilters({ severity: value as SeverityFilter })}
              options={[
                { value: "all", label: "All severities" },
                { value: "critical", label: "Critical" },
                { value: "high", label: "High" },
                { value: "medium", label: "Medium" },
                { value: "low", label: "Low" },
              ]}
            />
            <FilterSelect
              label="Status"
              value={filters.status}
              onChange={(value) => updateFilters({ status: value as StatusFilter })}
              options={[
                { value: "all", label: "All statuses" },
                { value: "new", label: "New" },
                { value: "investigating", label: "Investigating" },
                { value: "acknowledged", label: "Acknowledged" },
                { value: "resolved", label: "Resolved" },
              ]}
            />

            <label className="flex flex-col gap-1">
              <span className="font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
                From
              </span>
              <input
                type="date"
                value={filters.from}
                onChange={(event) => updateFilters({ from: event.target.value })}
                className="h-9 rounded-lg border border-cyber-border/80 bg-cyber-surface/70 px-2.5 font-data text-[12px] text-slate-200 focus:border-cyber-accent/40 focus:outline-none"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
                To
              </span>
              <input
                type="date"
                value={filters.to}
                onChange={(event) => updateFilters({ to: event.target.value })}
                className="h-9 rounded-lg border border-cyber-border/80 bg-cyber-surface/70 px-2.5 font-data text-[12px] text-slate-200 focus:border-cyber-accent/40 focus:outline-none"
              />
            </label>

            <label className="group flex min-w-[200px] flex-1 flex-col gap-1">
              <span className="font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
                Search
              </span>
              <span className="relative block">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-cyber-muted group-focus-within:text-cyber-accent"
                  strokeWidth={2}
                  aria-hidden="true"
                />
                <input
                  type="search"
                  value={filters.query}
                  onChange={(event) => updateFilters({ query: event.target.value })}
                  placeholder="Event ID, host, attack label..."
                  className="glass-inset h-9 w-full rounded-lg pl-9 pr-3 text-[12px] text-slate-100 placeholder:text-cyber-muted/70 focus:border-cyber-accent/40 focus:outline-none"
                />
              </span>
            </label>

            <div className="flex items-center gap-2">
              {activeFilterCount > 0 && (
                <button
                  type="button"
                  onClick={resetFilters}
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-cyber-border/70 bg-cyber-surface/60 px-3 font-data text-[11px] text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100"
                >
                  <RotateCcw className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                  Reset ({activeFilterCount})
                </button>
              )}
              <button
                type="button"
                onClick={exportCsv}
                className="flex h-9 items-center gap-2 rounded-lg border border-cyber-accent/30 bg-cyber-accent/10 px-3.5 font-data text-[11px] font-medium text-cyber-accent-bright hover:bg-cyber-accent/20"
              >
                <Download className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                Export CSV
              </button>
            </div>
          </div>
        </GlassCard>

        {/* ---------------------------------------------------------------- */}
        {/* Results table                                                     */}
        {/* ---------------------------------------------------------------- */}
        <GlassCard className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-cyber-border/60 px-5 py-3.5">
            <h2 className="font-data text-[11px] tracking-[0.22em] text-cyber-muted uppercase">
              Detection Queue
            </h2>
            <p className="font-data text-[10.5px] tabular text-cyber-muted">
              {sorted.length} events
              {activeFilterCount > 0 && (
                <span className="text-cyber-accent"> · {activeFilterCount} filters on</span>
              )}
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1020px] border-collapse text-left">
              <thead>
                <tr className="border-b border-cyber-border/60 bg-cyber-surface/40">
                  {COLUMNS.map((column) => {
                    const active = sortKey === column.key;
                    const SortIcon = !active
                      ? ChevronsUpDown
                      : sortDir === "desc"
                        ? ChevronDown
                        : ChevronUp;
                    return (
                      <th key={column.key} className="px-4 py-3 first:pl-5">
                        <button
                          type="button"
                          onClick={() => toggleSort(column.key)}
                          className={clsx(
                            "inline-flex items-center gap-1.5 font-data text-[10px] tracking-[0.16em] uppercase",
                            active
                              ? "text-cyber-accent"
                              : "text-cyber-muted hover:text-slate-200",
                          )}
                        >
                          {column.label}
                          <SortIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
                        </button>
                      </th>
                    );
                  })}
                  <th className="w-10 px-4 py-3" aria-label="Open details" />
                </tr>
              </thead>
              <tbody className="divide-y divide-cyber-border/40">
                {paged.map((event) => (
                  <tr
                    key={event.id}
                    onClick={() => setSelected(event)}
                    className="group cursor-pointer transition-colors hover:bg-cyber-overlay/40"
                  >
                    <td className="px-4 py-3 first:pl-5">
                      <p className="font-data text-[12px] tabular text-slate-100">
                        {formatClockUTC(event.timestamp)}
                      </p>
                      <p className="font-data text-[10px] text-cyber-muted">
                        {event.id} · UTC
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-data text-[12px] text-slate-100">{event.source}</p>
                      <p className="font-data text-[10px] text-cyber-muted">{event.sourceIp}</p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-data text-[12px] text-slate-100">
                        {event.destination}
                      </p>
                      <p className="font-data text-[10px] text-cyber-muted">
                        {event.destinationIp} · {event.protocol}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <CategoryChip category={event.category} size="sm" />
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-data text-[12px] text-slate-100">{event.attackType}</p>
                      <p
                        className="font-data text-[10px] capitalize"
                        style={{ color: SEVERITY_HEX[event.severity] }}
                      >
                        {event.severity}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="h-1 w-12 overflow-hidden rounded-full bg-cyber-border/60">
                          <span
                            className="block h-full rounded-full bg-cyber-accent"
                            style={{ width: `${event.confidence * 100}%` }}
                          />
                        </span>
                        <span className="font-data text-[11.5px] tabular text-slate-200">
                          {formatPercent(event.confidence * 100)}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={clsx(
                          "font-data text-[13px] font-semibold tabular",
                          riskTextClass(event.riskScore),
                        )}
                      >
                        {event.riskScore}
                      </span>
                      <span className="font-data text-[10px] text-cyber-muted">/100</span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusChip status={event.status} size="sm" />
                    </td>
                    <td className="px-4 py-3">
                      <ChevronRight
                        className="h-4 w-4 text-cyber-muted opacity-40 transition-opacity group-hover:opacity-100"
                        strokeWidth={2}
                        aria-hidden="true"
                      />
                    </td>
                  </tr>
                ))}
                {paged.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-5 py-12 text-center">
                      <p className="font-data text-[12px] text-cyber-muted">
                        No detections match the current filters.
                      </p>
                      <button
                        type="button"
                        onClick={resetFilters}
                        className="mt-3 rounded-lg border border-cyber-accent/30 bg-cyber-accent/10 px-4 py-1.5 font-data text-[11px] text-cyber-accent-bright hover:bg-cyber-accent/20"
                      >
                        Reset filters
                      </button>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-cyber-border/60 px-5 py-3.5">
            <p className="font-data text-[11px] tabular text-cyber-muted">
              Showing <span className="text-slate-200">{rangeStart}</span>–
              <span className="text-slate-200">{rangeEnd}</span> of{" "}
              <span className="text-slate-200">{sorted.length}</span>
            </p>

            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 font-data text-[11px] text-cyber-muted">
                Rows
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                  className="h-8 rounded-lg border border-cyber-border/80 bg-cyber-surface/70 px-2 font-data text-[11px] text-slate-200 focus:border-cyber-accent/40 focus:outline-none"
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </label>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={safePage <= 1}
                  aria-label="Previous page"
                  className="rounded-lg border border-cyber-border/70 bg-cyber-surface/60 p-1.5 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  <ChevronLeft className="h-4 w-4" strokeWidth={2} />
                </button>
                <span className="font-data text-[11px] tabular text-cyber-muted">
                  Page <span className="text-slate-200">{safePage}</span> / {pageCount}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                  disabled={safePage >= pageCount}
                  aria-label="Next page"
                  className="rounded-lg border border-cyber-border/70 bg-cyber-surface/60 p-1.5 text-cyber-muted hover:border-cyber-accent/30 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  <ChevronRight className="h-4 w-4" strokeWidth={2} />
                </button>
              </div>
            </div>
          </div>
        </GlassCard>
      </div>

      <InvestigationDrawer event={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

/* -------------------------------------------------------------------------- */
/*  Filter select                                                              */
/* -------------------------------------------------------------------------- */

interface FilterSelectProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}

function FilterSelect({ label, value, onChange, options }: FilterSelectProps) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-data text-[9.5px] tracking-[0.18em] text-cyber-muted uppercase">
        {label}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-lg border border-cyber-border/80 bg-cyber-surface/70 px-2.5 text-[12px] text-slate-200 focus:border-cyber-accent/40 focus:outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-cyber-elevated">
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
