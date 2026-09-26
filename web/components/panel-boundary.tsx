"use client";

import { WarningOctagon } from "@phosphor-icons/react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { RetryButton } from "./retry-button";
import { FailureMessage } from "./states";
import { cx, ICON } from "./ui";

/** Fences one panel: a render exception replaces this panel with a failure state, never the page. */
export class PanelBoundary extends Component<{ title: string; className?: string; children: ReactNode }, { error: (Error & { digest?: string }) | null }> {
  state = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Panel "${this.props.title}" failed to render`, error, info.componentStack);
  }

  render() {
    const { error } = this.state as { error: (Error & { digest?: string }) | null };
    if (!error) return this.props.children;
    return (
      <section aria-label={this.props.title} className={cx("min-w-0 bg-surface p-4 md:p-5", this.props.className)}>
        <h2 className="text-sm font-semibold text-ink">{this.props.title}</h2>
        <FailureMessage
          compact
          icon={<WarningOctagon size={20} {...ICON} aria-hidden />}
          title="This panel failed to render"
          body="Something unexpected went wrong while drawing it. The rest of the page is unaffected. Retry reloads just the data behind this page."
          actions={
            <>
              <RetryButton onRetry={() => this.setState({ error: null })} />
              {error.digest ? <span className="font-mono text-xs text-subtle">Reference {error.digest}</span> : null}
            </>
          }
        />
      </section>
    );
  }
}
