import type { ReactNode } from "react";

export function LoadingBlock({ label = "Working…" }: { label?: string }) {
  return (
    <div className="loading-block" role="status" aria-live="polite">
      <div>{label}</div>
      <div className="skeleton" style={{ width: "60%" }} />
      <div className="skeleton" style={{ width: "40%" }} />
      <div className="skeleton" style={{ width: "80%" }} />
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="banner banner-error" role="alert">
      {message}
    </div>
  );
}

export function InfoBanner({ message }: { message: string }) {
  return <div className="banner banner-info">{message}</div>;
}

export function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="banner banner-success" role="status">
      {message}
    </div>
  );
}
