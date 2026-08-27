import { useMemo, useState, type ReactNode } from "react";

export type SortDirection = "asc" | "desc";

type Sortable = string | number | boolean | null | undefined;

export type DataTableColumn<T> = {
  key: string;
  header: string;
  mono?: boolean;
  /** When false, header is not interactive. Default true. */
  sortable?: boolean;
  /** Prefer numeric/raw values for correct ordering of money and rates. */
  sortValue?: (row: T) => Sortable;
  render: (row: T) => ReactNode;
};

type Props<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T, i: number) => string;
  selectedKey?: string | null;
  onSelect?: (row: T) => void;
  caption?: string;
};

function nodeSortFallback(node: ReactNode): Sortable {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return node;
  if (Array.isArray(node)) {
    return node.map(nodeSortFallback).join(" ");
  }
  return "";
}

function coerceSortKey(value: Sortable): string | number {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : "";
  const trimmed = value.trim();
  if (!trimmed || trimmed === "—") return "";
  const cleaned = trimmed.replace(/[$,%\s]/g, "").replace(/,/g, "");
  if (cleaned !== "" && /^-?\d+(\.\d+)?$/.test(cleaned)) {
    return Number(cleaned);
  }
  return trimmed.toLowerCase();
}

function compareKeys(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;
  if (typeof b === "number") return 1;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  selectedKey,
  onSelect,
  caption,
}: Props<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDirection>("asc");

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col || col.sortable === false) return rows;
    const decorated = rows.map((row, i) => ({
      row,
      i,
      key: coerceSortKey(
        col.sortValue ? col.sortValue(row) : nodeSortFallback(col.render(row)),
      ),
    }));
    decorated.sort((a, b) => {
      const cmp = compareKeys(a.key, b.key);
      if (cmp !== 0) return sortDir === "asc" ? cmp : -cmp;
      return a.i - b.i;
    });
    return decorated.map((d) => d.row);
  }, [columns, rows, sortDir, sortKey]);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return (
    <div className="table-wrap">
      <table className="data">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => {
              const sortable = c.sortable !== false;
              const active = sortKey === c.key;
              const ariaSort = !sortable
                ? undefined
                : active
                  ? sortDir === "asc"
                    ? "ascending"
                    : "descending"
                  : "none";
              return (
                <th
                  key={c.key}
                  className={c.mono ? "mono" : undefined}
                  scope="col"
                  aria-sort={ariaSort}
                >
                  {sortable ? (
                    <button
                      type="button"
                      className="th-sort"
                      onClick={() => toggleSort(c.key)}
                    >
                      <span>{c.header}</span>
                      <span
                        className={
                          active
                            ? `th-sort-mark th-sort-mark-${sortDir}`
                            : "th-sort-mark th-sort-mark-none"
                        }
                        aria-hidden="true"
                      />
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>No rows</td>
            </tr>
          ) : (
            sortedRows.map((row, i) => {
              const key = rowKey(row, i);
              return (
                <tr
                  key={key}
                  className={selectedKey === key ? "selected" : undefined}
                  onClick={onSelect ? () => onSelect(row) : undefined}
                  style={onSelect ? { cursor: "pointer" } : undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.mono ? "mono" : undefined}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
