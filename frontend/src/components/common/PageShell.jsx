/** components/common/PageShell.jsx */

export function PageShell({ title, action, children }) {
  return (
    <div style={{ padding: "24px" }}>
      {(title || action) && (
        <div className="page-header">
          {title && <h1 className="page-title">{title}</h1>}
          {action && <div>{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

export default PageShell;
