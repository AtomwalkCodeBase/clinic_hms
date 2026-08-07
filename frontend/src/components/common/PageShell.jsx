/**
 * components/common/PageShell.jsx
 * --------------------------------
 * Standard page wrapper used by every role page.
 * Provides consistent padding, page title, and an optional action button.
 *
 * Props:
 *   title      — page heading string
 *   action     — optional ReactNode (e.g. a primary button) placed top-right
 *   children   — page content
 */

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
