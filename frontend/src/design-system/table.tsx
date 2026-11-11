/*
 * Semantic data table: <caption>, <th scope="col">, sortable headers expose
 * aria-sort and are real buttons. Wide tables scroll horizontally inside a
 * focusable, labelled region so keyboard users can scroll them.
 */
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useId, type ReactNode } from "react";

import { cx } from "./primitives";

export type SortDirection = "ascending" | "descending";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  numeric?: boolean;
  /** Render the cell as a row header (<th scope="row">). */
  rowHeader?: boolean;
  width?: string;
  /** The column name shown beside the cell when the table is stacked on a narrow screen (`stackOnMobile`). */
  label?: string;
}

export function DataTable<T>({
  caption,
  captionHidden,
  columns,
  rows,
  rowKey,
  sort,
  onSort,
  empty,
  stackOnMobile,
  align = "middle",
}: {
  caption: string;
  captionHidden?: boolean;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  sort?: { key: string; direction: SortDirection };
  onSort?: (key: string) => void;
  empty?: ReactNode;
  /** On narrow screens each row becomes a block with the column names as labels (the table semantics stay). */
  stackOnMobile?: boolean;
  /** Vertical alignment of the cells – «top» for rows with uneven content. */
  align?: "middle" | "top";
}) {
  const captionId = useId();
  return (
    <div className="ek-table-wrap" role="region" aria-labelledby={captionId} tabIndex={0}>
      <table className={cx("ek-table", stackOnMobile && "ek-table--stack", align === "top" && "ek-table--top")}>
        <caption id={captionId} className={captionHidden ? "ek-visually-hidden" : undefined}>
          {caption}
        </caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={cx(column.numeric && "ek-table__num")}
                  style={column.width ? { width: column.width } : undefined}
                  aria-sort={column.sortable ? (active ? sort?.direction : "none") : undefined}
                >
                  {column.sortable && onSort ? (
                    <button type="button" className="ek-table__sort" onClick={() => onSort(column.key)}>
                      {column.header}
                      {active ? (
                        sort?.direction === "ascending" ? (
                          <ArrowUp aria-hidden="true" size={14} />
                        ) : (
                          <ArrowDown aria-hidden="true" size={14} />
                        )
                      ) : (
                        <ArrowUpDown aria-hidden="true" size={14} />
                      )}
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="ek-muted">
                {empty ?? "Ingen rader å vise."}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) =>
                  column.rowHeader ? (
                    <th key={column.key} scope="row" className={cx(column.numeric && "ek-table__num")}
                      data-label={column.label ?? (typeof column.header === "string" ? column.header : undefined)}>
                      {column.cell(row)}
                    </th>
                  ) : (
                    <td key={column.key} className={cx(column.numeric && "ek-table__num")}
                      data-label={column.label ?? (typeof column.header === "string" ? column.header : undefined)}>
                      {column.cell(row)}
                    </td>
                  ),
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function nextSort(
  current: { key: string; direction: SortDirection } | undefined,
  key: string,
): { key: string; direction: SortDirection } {
  if (current?.key === key) {
    return { key, direction: current.direction === "ascending" ? "descending" : "ascending" };
  }
  return { key, direction: "ascending" };
}
