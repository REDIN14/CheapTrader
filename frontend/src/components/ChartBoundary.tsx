// Keeps a failure inside the chart from taking the whole screen with it.
//
// If drawing the candles throws (a series the chart cannot take, whatever the cause),
// React would unmount the entire app and leave a blank page, with the trader's
// positions and the order buttons gone. This catches it, says so in the console,
// and builds the chart again from the candles the app still holds — which is all it
// takes, since nothing the chart knows is kept only in the chart. If it keeps failing
// (more than a few times in a few seconds) it stops trying and says so instead of
// looping.

import { Component, type ReactNode } from "react";

interface Props {
  /** Renders the chart; `generation` changes every time it has to be rebuilt (use it as a key). */
  children: (generation: number) => ReactNode;
}

interface State {
  broken: boolean;
  generation: number;
  failures: number[];
}

const MAX_FAILURES = 3;
const WINDOW_MS = 10_000;

export class ChartBoundary extends Component<Props, State> {
  state: State = { broken: false, generation: 0, failures: [] };

  static getDerivedStateFromError(): Partial<State> {
    return { broken: true };
  }

  componentDidCatch(error: Error): void {
    console.error("The chart failed and is being rebuilt:", error);
    const now = Date.now();
    this.setState((s) => {
      const failures = [...s.failures.filter((t) => now - t < WINDOW_MS), now];
      return failures.length > MAX_FAILURES
        ? { ...s, failures }
        : { broken: false, generation: s.generation + 1, failures };
    });
  }

  render(): ReactNode {
    if (this.state.broken) {
      return this.state.failures.length > MAX_FAILURES ? (
        <div className="chart-failed" role="alert">
          The chart stopped working. Reload the page to bring it back.
        </div>
      ) : null;
    }
    return this.props.children(this.state.generation);
  }
}
