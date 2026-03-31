import { Card, CardHeader, CardBody, Badge } from "@/components/ui";

const RECENT_ACTIVITY = [
  { id: "1", text: "New todo added to Job Search", time: "2 min ago", type: "info" as const },
  { id: "2", text: "Marketing campaign status changed", time: "15 min ago", type: "success" as const },
  { id: "3", text: "Side Project build failed", time: "1 hr ago", type: "danger" as const },
  { id: "4", text: "Reading List updated", time: "3 hr ago", type: "default" as const },
];

function Home() {
  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-[var(--text-2xl)] font-bold text-[var(--color-text-primary)]">
          Command Center
        </h1>
        <p className="text-[var(--text-sm)] text-[var(--color-text-tertiary)] font-mono mt-1">
          // System overview
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: "SPACES", value: "5", accent: true },
          { label: "TODOS", value: "12", accent: false },
          { label: "ACTIVE", value: "3", accent: false },
          { label: "AGENTS", value: "0", accent: false },
        ].map((stat) => (
          <Card key={stat.label}>
            <CardBody className="!py-3 !px-3">
              <span className="text-[var(--text-xs)] font-mono font-medium text-[var(--color-text-tertiary)] tracking-wider">
                {stat.label}
              </span>
              <div
                className={[
                  "text-[var(--text-2xl)] font-bold font-mono mt-0.5",
                  stat.accent
                    ? "text-[var(--color-accent-text)]"
                    : "text-[var(--color-text-primary)]",
                ].join(" ")}
              >
                {stat.value}
              </div>
            </CardBody>
          </Card>
        ))}
      </div>

      {/* Recent activity */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <span>Recent Activity</span>
            <Badge variant="info">{RECENT_ACTIVITY.length} events</Badge>
          </div>
        </CardHeader>
        <CardBody className="!p-0">
          <div className="divide-y divide-[var(--color-border-subtle)]">
            {RECENT_ACTIVITY.map((activity) => (
              <div
                key={activity.id}
                className="flex items-center justify-between px-4 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors"
              >
                <div className="flex items-center gap-3">
                  <Badge variant={activity.type}>
                    {activity.type === "info" && "NEW"}
                    {activity.type === "success" && "OK"}
                    {activity.type === "danger" && "ERR"}
                    {activity.type === "default" && "UPD"}
                  </Badge>
                  <span className="text-[var(--text-sm)] text-[var(--color-text-primary)]">
                    {activity.text}
                  </span>
                </div>
                <span className="text-[var(--text-xs)] text-[var(--color-text-tertiary)] font-mono shrink-0">
                  {activity.time}
                </span>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

export default Home;
