import { useMemo, useRef, useState } from 'react';
import { $api } from '../../api/hooks';
import { Card, CardBody } from '../ui';

/** Compact sparkline of daily token usage. */
export function TokenSparkline() {
  const daily = $api.useQuery('get', '/api/v1/stats/tokens/daily', {
    params: { query: { days: 7 } },
  }, {
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Also grab 24h stats for the summary line
  const last24h = $api.useQuery('get', '/api/v1/stats/tokens', {
    params: { query: { period: '24h' } },
  }, {
    staleTime: 60_000,
  });

  if (daily.isLoading) {
    return (
      <Card>
        <CardBody className="space-y-2">
          <div className="h-3 w-24 rounded bg-raised animate-pulse" />
          <div className="h-10 w-full rounded bg-raised animate-pulse" />
          <div className="h-3 w-32 rounded bg-raised animate-pulse" />
        </CardBody>
      </Card>
    );
  }

  const buckets = daily.data?.buckets ?? [];
  const last24hTotal = last24h.data?.total_tokens ?? 0;

  return (
    <Card>
      <CardBody className="space-y-2">
        <div className="text-xs text-muted">7-day trend</div>
        <SparklineSVG buckets={buckets} />
        <div className="text-xs text-muted tabular-nums">
          Last 24h: {formatTokenCount(last24hTotal)} tokens
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sparkline SVG
// ---------------------------------------------------------------------------

interface Bucket {
  date: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

const SVG_WIDTH = 200;
const SVG_HEIGHT = 40;
const PADDING_X = 4;
const PADDING_Y = 4;

function SparklineSVG({ buckets }: { buckets: Bucket[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(null);

  const points = useMemo(() => {
    if (buckets.length === 0) return [];

    const values = buckets.map((b) => b.total_tokens);
    const max = Math.max(...values, 1); // avoid division by zero
    const usableW = SVG_WIDTH - PADDING_X * 2;
    const usableH = SVG_HEIGHT - PADDING_Y * 2;
    const step = buckets.length > 1 ? usableW / (buckets.length - 1) : 0;

    return values.map((v, i) => ({
      x: PADDING_X + i * step,
      y: PADDING_Y + usableH - (v / max) * usableH,
    }));
  }, [buckets]);

  if (buckets.length === 0) {
    return (
      <div className="h-10 flex items-center justify-center">
        <span className="text-xs text-muted italic">No token data yet</span>
      </div>
    );
  }

  // Build the polyline path
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
  // Build the fill area (closed path down to baseline)
  const fillPath = `${linePath} L${points[points.length - 1].x},${SVG_HEIGHT - PADDING_Y} L${points[0].x},${SVG_HEIGHT - PADDING_Y} Z`;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mouseX = ((e.clientX - rect.left) / rect.width) * SVG_WIDTH;

    // Find the closest point
    let closest = 0;
    let minDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(points[i].x - mouseX);
      if (dist < minDist) {
        minDist = dist;
        closest = i;
      }
    }

    // Get position relative to container for tooltip placement
    const containerRect = containerRef.current?.getBoundingClientRect();
    if (containerRect) {
      setHover({
        idx: closest,
        x: e.clientX - containerRect.left,
        y: e.clientY - containerRect.top,
      });
    }
  };

  const hoveredBucket = hover !== null ? buckets[hover.idx] : null;

  return (
    <div ref={containerRef} className="relative">
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="w-full h-10 cursor-crosshair"
        preserveAspectRatio="none"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHover(null)}
      >
        {/* Gradient fill under the line */}
        <defs>
          <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--t-accent)" stopOpacity="0.2" />
            <stop offset="100%" stopColor="var(--t-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={fillPath} fill="url(#sparkFill)" />
        <path d={linePath} fill="none" stroke="var(--t-accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />

        {/* Hover dot */}
        {hover !== null && points[hover.idx] && (
          <circle
            cx={points[hover.idx].x}
            cy={points[hover.idx].y}
            r="3"
            fill="var(--t-accent)"
            stroke="var(--t-surface)"
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {/* Tooltip */}
      {hover !== null && hoveredBucket && (
        <div
          className="absolute z-10 pointer-events-none px-2.5 py-1.5 rounded-md bg-surface border border-border shadow-lg text-xs whitespace-nowrap"
          style={{
            left: `${Math.min(hover.x, (containerRef.current?.clientWidth ?? 200) - 120)}px`,
            top: '-36px',
          }}
        >
          <span className="text-muted">{formatDate(hoveredBucket.date)}</span>
          <span className="mx-1.5 text-border">|</span>
          <span className="text-foreground font-medium tabular-nums">
            {formatTokenCount(hoveredBucket.total_tokens)}
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function formatDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
