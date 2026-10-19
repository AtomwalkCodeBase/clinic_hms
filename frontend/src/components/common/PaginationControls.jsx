/** components/common/PaginationControls.jsx */
const PAGE_SIZE_OPTIONS = [5, 10, 15, 20, 25];

export default function PaginationControls({
  pagination, page, pageSize, onPageChange, onPageSizeChange,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
}) {
  if (!pagination) return null;
  const { total_pages = 1, has_next = false, has_previous = false, total_count } = pagination;

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      flexWrap: "wrap", gap: 12, padding: "14px 20px", borderTop: "1px solid var(--color-border)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--color-text-muted)" }}>
        <span>Show</span>
        <select
          className="form-input" style={{ padding: "4px 8px", fontSize: 12, width: "auto" }}
          value={pageSize}
          onChange={e => {
            onPageSizeChange(Number(e.target.value));
            onPageChange(1);
          }}
        >
          {pageSizeOptions.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <span>per page{typeof total_count === "number" ? ` · ${total_count} total` : ""}</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
          disabled={!has_previous} onClick={() => onPageChange(Math.max(1, page - 1))}>
          ← Previous
        </button>
        <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
          Page {page} of {total_pages}
        </span>
        <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
          disabled={!has_next} onClick={() => onPageChange(Math.min(total_pages, page + 1))}>
          Next →
        </button>
      </div>
    </div>
  );
}
