/** components/common/ErrorBoundary.jsx */
import { Component } from "react";

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // Logged to the console for now — swap for a real error-tracking
     
    console.error("ErrorBoundary caught a render error:", error, info?.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center",
          padding: 24,
        }}>
          <div className="card" style={{ maxWidth: 440, padding: 32, textAlign: "center" }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 8, color: "var(--color-error, #b91c1c)" }}>
              Something went wrong on this page.
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 20, lineHeight: 1.5 }}>
              This page hit an unexpected error and couldn't render. Your session and data are fine —
              try reloading this page, or head back and try again.
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button className="btn btn--secondary" onClick={this.handleReset}>Try again</button>
              <button className="btn-primary" onClick={() => window.location.reload()}>Reload page</button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
