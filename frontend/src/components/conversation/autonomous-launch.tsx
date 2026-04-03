import { useState } from 'react';
import { $api } from '../../api/hooks';
import { Button } from '../ui';

interface AutonomousLaunchProps {
  agentId: string;
  agentName: string;
  /** Called with the conversation_id and task_id after launch succeeds */
  onLaunched: (conversationId: string, taskId: string) => void;
}

const TIME_BUDGET_OPTIONS = [
  { label: '1 hour', value: 3600 },
  { label: '2 hours', value: 7200 },
  { label: '4 hours', value: 14400 },
  { label: '8 hours', value: 28800 },
  { label: 'No limit', value: 0 },
] as const;

export function AutonomousLaunch({ agentId, agentName, onLaunched }: AutonomousLaunchProps) {
  const [goal, setGoal] = useState('');
  const [showOptions, setShowOptions] = useState(false);
  const [constraints, setConstraints] = useState('');
  const [tokenBudget, setTokenBudget] = useState<number | null>(null);
  const [timeBudget, setTimeBudget] = useState<number>(0);

  const launchMutation = $api.useMutation('post', '/api/v1/agents/{agent_id}/autonomous');

  const canSubmit = goal.trim().length > 0 && !launchMutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) return;

    launchMutation.mutate(
      {
        params: { path: { agent_id: agentId } },
        body: {
          goal: goal.trim(),
          constraints: constraints.trim() || null,
          token_budget: tokenBudget,
          time_budget: timeBudget > 0 ? timeBudget : null,
        },
      },
      {
        onSuccess: (data) => {
          onLaunched(data.conversation_id, data.task_id);
        },
      },
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="px-4 py-6 bg-surface border-b border-border">
      {/* Agent context */}
      <div className="flex items-center gap-2 mb-4">
        <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-primary/15 text-primary text-xs font-bold shrink-0">
          {agentName.charAt(0).toUpperCase()}
        </span>
        <span className="text-sm text-muted">
          Launch autonomous run with <span className="text-foreground font-medium">{agentName}</span>
        </span>
      </div>

      {/* Goal input */}
      <div className="mb-3">
        <label htmlFor="autonomous-goal" className="block text-sm font-medium text-foreground mb-1.5">
          What goal should this agent pursue?
        </label>
        <textarea
          id="autonomous-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe the goal in plain language..."
          rows={3}
          className="w-full resize-none bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          autoFocus
        />
      </div>

      {/* Expandable options */}
      <div className="mb-4">
        <button
          type="button"
          onClick={() => setShowOptions(!showOptions)}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-foreground transition-colors cursor-pointer"
        >
          <span
            className="transition-transform duration-150"
            style={{ transform: showOptions ? 'rotate(90deg)' : 'rotate(0deg)' }}
          >
            &#9654;
          </span>
          Options
        </button>

        {showOptions && (
          <div className="mt-3 space-y-3 pl-4 border-l-2 border-border">
            {/* Constraints */}
            <div>
              <label htmlFor="autonomous-constraints" className="block text-xs font-medium text-foreground mb-1">
                Constraints
              </label>
              <textarea
                id="autonomous-constraints"
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
                placeholder="Any restrictions or guidelines..."
                rows={2}
                className="w-full resize-none bg-raised text-foreground border border-border rounded-md px-3 py-2 text-xs placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
              />
            </div>

            {/* Token budget */}
            <div>
              <label htmlFor="autonomous-token-budget" className="block text-xs font-medium text-foreground mb-1">
                Token budget
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="autonomous-token-budget"
                  type="number"
                  value={tokenBudget ?? ''}
                  onChange={(e) => setTokenBudget(e.target.value ? Number(e.target.value) : null)}
                  placeholder="No limit"
                  min={1000}
                  step={1000}
                  className="w-36 bg-raised text-foreground border border-border rounded-md px-3 py-1.5 text-xs placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
                />
                {tokenBudget != null && (
                  <span className="text-[11px] text-muted">
                    ~{(tokenBudget / 1000).toFixed(0)}k tokens
                  </span>
                )}
              </div>
            </div>

            {/* Time budget */}
            <div>
              <label htmlFor="autonomous-time-budget" className="block text-xs font-medium text-foreground mb-1">
                Time budget
              </label>
              <select
                id="autonomous-time-budget"
                value={timeBudget}
                onChange={(e) => setTimeBudget(Number(e.target.value))}
                className="bg-raised text-foreground text-xs border border-border rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary cursor-pointer"
              >
                {TIME_BUDGET_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Submit */}
      <div className="flex items-center gap-3">
        <Button
          size="md"
          variant="primary"
          onClick={handleSubmit}
          disabled={!canSubmit}
          loading={launchMutation.isPending}
        >
          Start
        </Button>
        <span className="text-[11px] text-muted">
          {launchMutation.isPending
            ? 'Starting clarification conversation...'
            : 'The agent will ask clarifying questions before running.'}
        </span>
      </div>

      {/* Error */}
      {launchMutation.isError && (
        <p className="mt-2 text-xs text-destructive">
          Failed to launch: {(launchMutation.error as Error)?.message ?? 'Unknown error'}
        </p>
      )}
    </div>
  );
}
