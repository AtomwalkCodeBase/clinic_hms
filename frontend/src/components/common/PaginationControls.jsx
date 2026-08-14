/**
 * components/common/PaginationControls.jsx
 * -------------------------------------------
 * Reusable pagination footer: a page-size picker (5 / 10 / 15 / 20 / 25) plus
 * Previous / Next buttons and a "Page X of Y" label. Pairs with the backend's
 * `paginate_queryset` helper (core/pagination.py), which already reads
 * ?page=&page_size= and returns { page, page_size, total_count, total_pages,
 * has_next, has_previous } — this component just renders that meta and
 * reports page/page_size changes back to the caller.
 *
 * Usage:
 *   const [page, setPage] = useState(1);
 *   const [pageSize, setPageSize] = useState(10);
 *   const { data } = useApi(ENDPOINT, { params: { page, page_size: pageSize } });
 *   <PaginationControls
 *     pagination={data?.pagination}
 *     page={page} pageSize={pageSize}
 *     onPageChange={setPage} onPageSizeChange={setPageSize}
 *   />
 */
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
