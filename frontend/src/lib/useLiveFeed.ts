// The live market as the screen sees it.
//
// Ticks and account updates arrive from the server whenever the terminal has
// something new, many times a second in a busy market. Drawing each one the moment it
// arrives would only make the browser do work nobody can see, so they are collected
// and handed to React once per animation frame: the screen is always as up to date as
// it can be shown, and nothing is lost on the way — a frame gets *all* the ticks that
// arrived since the last one (the chart folds every one into the candle, so highs and
// lows are the terminal's, not a sample of them).

import { useEffect, useRef, useState } from "react";
import { StreamClient, type StreamState } from "./ws";
import type { Tick } from "./types";

const WS_URL = import.meta.env.VITE_WS_BASE ?? "";

/** Ticks held for a frame that never comes (a hidden tab) before the oldest are let go. */
const MAX_HELD = 20_000;
/** A frame is forced after this long even if the browser is not painting (a hidden tab). */
const MAX_WAIT_MS = 250;

export interface LiveFeed {
  /** The newest tick of the symbol; null until the first one arrives. */
  tick: Tick | null;
  /** Every tick that arrived since the previous frame, oldest first. */
  ticks: Tick[];
  /** The stream is connected to the server. */
  connected: boolean;
  /** The server's feed from MetaTrader is running (false while it restarts after a failure). */
  feedUp: boolean;
  /** MetaTrader is taking seconds to answer (another program is working it hard): prices come, but late. */
  feedSlow: boolean;
}

interface Options {
  symbol: string | null;
  /** False while a replay owns the chart: the stream is closed. */
  enabled: boolean;
  /** The account or the positions changed. Called at most once per frame. */
  onState: (state: StreamState) => void;
  /** The stream (re)connected: what happened while it was down may have been missed. */
  onReconnect?: () => void;
}

const NONE: Pick<LiveFeed, "tick" | "ticks"> = { tick: null, ticks: [] };

export function useLiveFeed({ symbol, enabled, onState, onReconnect }: Options): LiveFeed {
  const [feed, setFeed] = useState(NONE);
  const [connected, setConnected] = useState(false);
  const [feedStatus, setFeedStatus] = useState("up");
  const callbacks = useRef({ onState, onReconnect });
  callbacks.current = { onState, onReconnect };

  useEffect(() => {
    setFeed(NONE);
    if (!symbol || !enabled) return;

    let held: Tick[] = [];
    let state: StreamState | null = null;
    let frame = 0;
    let timer = 0;
    let wasConnected = false;
    let feedWas = "up";

    const flush = () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      frame = 0;
      timer = 0;
      if (held.length) {
        const ticks = held;
        held = [];
        setFeed({ tick: ticks[ticks.length - 1], ticks });
      }
      if (state) {
        const next = state;
        state = null;
        callbacks.current.onState(next);
      }
    };
    const schedule = () => {
      if (frame || timer) return;
      frame = window.requestAnimationFrame(flush);
      timer = window.setTimeout(flush, MAX_WAIT_MS);
    };

    const client = new StreamClient(WS_URL);
    client.connect(symbol, {
      onTicks: (tickSymbol, ticks) => {
        if (tickSymbol !== symbol) return; // in flight from the symbol before
        for (const t of ticks) held.push(t);
        if (held.length > MAX_HELD) held = held.slice(held.length - MAX_HELD);
        schedule();
      },
      onState: (next) => {
        state = next;
        schedule();
      },
      onStatus: (up) => {
        setConnected(up);
        if (up && wasConnected) callbacks.current.onReconnect?.();
        if (up) wasConnected = true;
      },
      onFeed: (status) => {
        setFeedStatus(status);
        // A slow feed catches up by itself and nothing is lost; one that was down may have missed ticks.
        if (status === "up" && feedWas !== "slow") callbacks.current.onReconnect?.();
        feedWas = status;
      },
    });

    return () => {
      client.close();
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      setConnected(false);
      setFeedStatus("up");
    };
  }, [symbol, enabled]);

  return { ...feed, connected, feedUp: feedStatus === "up" || feedStatus === "slow", feedSlow: feedStatus === "slow" };
}
