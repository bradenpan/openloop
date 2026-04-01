import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { $api } from '../api/hooks';
import { api } from '../api/client';
import type { components } from '../api/types';
import { Card, CardBody, Badge, Button, Modal, Panel } from '../components/ui';

type Automation = components['schemas']['AutomationResponse'];
type AutomationRun = components['schemas']['AutomationRunResponse'];
type AutomationCreate = components['schemas']['AutomationCreate'];
type AutomationUpdate = components['schemas']['AutomationUpdate'];

// ─── Cron helpers ────────────────────────────────────────────────────────────

type CronPreset = 'daily' | 'weekly' | 'monthly' | 'custom';

function cronFromConfig(preset: CronPreset, hour: number, minute: number, dayOfWeek: number, dayOfMonth: number): string {
  switch (preset) {
    case 'daily':   return `${minute} ${hour} * * *`;
    case 'weekly':  return `${minute} ${hour} * * ${dayOfWeek}`;
    case 'monthly': return `${minute} ${hour} ${dayOfMonth} * *`;
    default:        return '';
  }
}

const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

function describePreset(preset: CronPreset, hour: number, minute: number, dayOfWeek: number, dayOfMonth: number): string {
  const timeStr = `${hour % 12 === 0 ? 12 : hour % 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`;
  switch (preset) {
    case 'daily':   return `Every day at ${timeStr}`;
    case 'weekly':  return `Every ${DAYS_OF_WEEK[dayOfWeek]} at ${timeStr}`;
    case 'monthly': return `Every month on day ${dayOfMonth} at ${timeStr}`;
    case 'custom':  return 'Custom schedule';
  }
}

function describeCron(expr: string | null | undefined): string {
  if (!expr) return '—';
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hr, dom, , dow] = parts;
  const h = parseInt(hr);
  const m = parseInt(min);
  if (isNaN(h) || isNaN(m)) return expr;
  const timeStr = `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
  if (dom === '*' && dow === '*') return `Every day at ${timeStr}`;
  if (dom === '*' && !isNaN(parseInt(dow))) return `Every ${DAYS_OF_WEEK[parseInt(dow) % 7] ?? dow} at ${timeStr}`;
  if (dow === '*' && !isNaN(parseInt(dom))) return `Every month on day ${dom} at ${timeStr}`;
  return expr;
}

// ─── Status helpers ───────────────────────────────────────────────────────────

function statusVariant(status: string | null | undefined): 'success' | 'danger' | 'warning' | 'info' | 'default' {
  switch (status) {
    case 'success':  return 'success';
    case 'failed':
    case 'error':    return 'danger';
    case 'running':
    case 'pending':  return 'warning';
    case 'skipped':  return 'info';
    default:         return 'default';
  }
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60)  return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function duration(run: AutomationRun): string {
  if (!run.completed_at) return '—';
  const ms = new Date(run.completed_at).getTime() - new Date(run.started_at).getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

// ─── Status dot (same animation pattern as BackgroundTaskCard) ─────────────

function StatusDot({ status }: { status: string | null | undefined }) {
  const isRunning = status === 'running' || status === 'pending';
  const color = status === 'success' ? 'bg-success'
    : (status === 'failed' || status === 'error') ? 'bg-destructive'
    : isRunning ? 'bg-warning'
    : status === null || status === undefined ? 'bg-muted'
    : 'bg-muted';

  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      {isRunning && (
        <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${color} opacity-75`} />
      )}
      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${color}`} />
    </span>
  );
}

// ─── Run history row ──────────────────────────────────────────────────────────

function RunRow({ run }: { run: AutomationRun }) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-border last:border-0">
      <StatusDot status={run.status} />
      <div className="flex-1 min-w-0">
        {run.result_summary && (
          <p className="text-xs text-foreground truncate">{run.result_summary}</p>
        )}
        {run.error && (
          <p className="text-xs text-destructive truncate">{run.error}</p>
        )}
        {!run.result_summary && !run.error && (
          <p className="text-xs text-muted">No summary</p>
        )}
      </div>
      <div className="shrink-0 text-right space-y-0.5">
        <Badge variant={statusVariant(run.status)} className="text-xs">{run.status}</Badge>
        <div className="text-[11px] text-muted tabular-nums">{timeAgo(run.started_at)}</div>
        <div className="text-[11px] text-muted tabular-nums">{duration(run)}</div>
      </div>
    </div>
  );
}

// ─── Automation form ──────────────────────────────────────────────────────────

interface FormState {
  name: string;
  description: string;
  agent_id: string;
  instruction: string;
  preset: CronPreset;
  cron_expression: string;
  hour: number;
  minute: number;
  dayOfWeek: number;
  dayOfMonth: number;
  space_id: string;
  model_override: string;
  enabled: boolean;
}

function defaultForm(): FormState {
  return {
    name: '',
    description: '',
    agent_id: '',
    instruction: '',
    preset: 'daily',
    cron_expression: '0 9 * * *',
    hour: 9,
    minute: 0,
    dayOfWeek: 1,
    dayOfMonth: 1,
    space_id: '',
    model_override: '',
    enabled: true,
  };
}

function automationToForm(a: Automation): FormState {
  // Detect preset from cron expression
  let preset: CronPreset = 'custom';
  let hour = 9, minute = 0, dayOfWeek = 1, dayOfMonth = 1;
  if (a.cron_expression) {
    const parts = a.cron_expression.trim().split(/\s+/);
    if (parts.length === 5) {
      const [min, hr, dom, , dow] = parts;
      minute = parseInt(min) || 0;
      hour   = parseInt(hr) || 9;
      if (dom === '*' && dow === '*') { preset = 'daily'; }
      else if (dom === '*' && !isNaN(parseInt(dow))) { preset = 'weekly'; dayOfWeek = parseInt(dow); }
      else if (dow === '*' && !isNaN(parseInt(dom))) { preset = 'monthly'; dayOfMonth = parseInt(dom); }
    }
  }
  return {
    name: a.name,
    description: a.description ?? '',
    agent_id: a.agent_id,
    instruction: a.instruction,
    preset,
    cron_expression: a.cron_expression ?? '',
    hour,
    minute,
    dayOfWeek,
    dayOfMonth,
    space_id: a.space_id ?? '',
    model_override: a.model_override ?? '',
    enabled: a.enabled,
  };
}

function formToCronExpression(f: FormState): string {
  if (f.preset === 'custom') return f.cron_expression;
  return cronFromConfig(f.preset, f.hour, f.minute, f.dayOfWeek, f.dayOfMonth);
}

interface AutomationFormProps {
  open: boolean;
  onClose: () => void;
  editing?: Automation | null;
  onSaved: () => void;
}

function AutomationForm({ open, onClose, editing, onSaved }: AutomationFormProps) {
  const [form, setForm] = useState<FormState>(editing ? automationToForm(editing) : defaultForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form when modal opens: populate from editing or reset to defaults
  useEffect(() => {
    if (open) {
      if (editing) {
        setForm(automationToForm(editing));
      } else {
        setForm(defaultForm());
      }
      setError(null);
    }
  }, [open, editing]);

  const agents = $api.useQuery('get', '/api/v1/agents', {}, { enabled: open });
  const spaces = $api.useQuery('get', '/api/v1/spaces', {}, { enabled: open });

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const applyPreset = (preset: CronPreset) => {
    if (preset === 'custom') {
      // Snapshot current schedule into cron expression before switching to custom
      setForm((prev) => ({
        ...prev,
        preset: 'custom',
        cron_expression: cronFromConfig(prev.preset, prev.hour, prev.minute, prev.dayOfWeek, prev.dayOfMonth) || prev.cron_expression,
      }));
      return;
    }
    set('preset', preset);
    if (preset === 'daily')   { set('cron_expression', '0 9 * * *'); }
    if (preset === 'weekly')  { set('cron_expression', '0 9 * * 1'); }
    if (preset === 'monthly') { set('cron_expression', '0 9 1 * *'); }
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.agent_id || !form.instruction.trim()) {
      setError('Name, agent, and instruction are required.');
      return;
    }

    const cronExpr = formToCronExpression(form);
    if (!cronExpr) {
      setError('A cron expression is required.');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const createBody: AutomationCreate = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        agent_id: form.agent_id,
        instruction: form.instruction.trim(),
        trigger_type: 'cron',
        cron_expression: cronExpr,
        space_id: form.space_id || undefined,
        model_override: form.model_override.trim() || undefined,
        enabled: form.enabled,
      };

      if (editing) {
        const updateBody: AutomationUpdate = {
          name: form.name.trim(),
          description: form.description.trim() || null,
          agent_id: form.agent_id,
          instruction: form.instruction.trim(),
          trigger_type: 'cron',
          cron_expression: cronExpr,
          space_id: form.space_id || null,
          model_override: form.model_override.trim() || null,
          enabled: form.enabled,
        };
        const res = await api.PATCH('/api/v1/automations/{automation_id}', {
          params: { path: { automation_id: editing.id } },
          body: updateBody,
        });
        if ((res as { error?: unknown }).error) throw new Error('Save failed');
      } else {
        const res = await api.POST('/api/v1/automations', { body: createBody });
        if ((res as { error?: unknown }).error) throw new Error('Save failed');
      }

      onSaved();
      onClose();
    } catch {
      setError('Failed to save automation.');
    } finally {
      setSaving(false);
    }
  };

  const cronPreview = form.preset !== 'custom'
    ? describePreset(form.preset, form.hour, form.minute, form.dayOfWeek, form.dayOfMonth)
    : describeCron(form.cron_expression);

  return (
    <Modal open={open} onClose={onClose} title={editing ? 'Edit Automation' : 'New Automation'} className="max-w-2xl">
      <div className="space-y-4">
        {error && <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-md">{error}</p>}

        {/* Name */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-name" className="text-sm font-medium text-foreground">Name <span className="text-destructive">*</span></label>
          <input
            id="automation-name"
            type="text"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="e.g. Daily standup digest"
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          />
        </div>

        {/* Description */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-description" className="text-sm font-medium text-foreground">Description</label>
          <input
            id="automation-description"
            type="text"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            placeholder="Optional description"
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          />
        </div>

        {/* Agent */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-agent" className="text-sm font-medium text-foreground">Agent <span className="text-destructive">*</span></label>
          <select
            id="automation-agent"
            value={form.agent_id}
            onChange={(e) => set('agent_id', e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          >
            <option value="">Select an agent…</option>
            {(agents.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        {/* Instruction */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-instruction" className="text-sm font-medium text-foreground">Instruction <span className="text-destructive">*</span></label>
          <textarea
            id="automation-instruction"
            value={form.instruction}
            onChange={(e) => set('instruction', e.target.value)}
            placeholder="What should the agent do when this runs?"
            rows={3}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150 resize-none"
          />
        </div>

        {/* Schedule */}
        <div className="flex flex-col gap-2" role="group" aria-labelledby="automation-schedule-label">
          <label id="automation-schedule-label" className="text-sm font-medium text-foreground">Schedule</label>
          <div className="flex gap-2">
            {(['daily', 'weekly', 'monthly', 'custom'] as CronPreset[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => applyPreset(p)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors duration-150 ${form.preset === p ? 'bg-primary text-primary-foreground' : 'bg-raised text-muted hover:text-foreground hover:bg-raised/80'}`}
              >
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
          </div>

          {form.preset !== 'custom' && (
            <div className="flex flex-wrap items-center gap-3 pt-1">
              {/* Time picker */}
              <div className="flex items-center gap-1.5">
                <label htmlFor="automation-hour" className="text-xs text-muted">Time</label>
                <select
                  id="automation-hour"
                  value={form.hour}
                  onChange={(e) => set('hour', parseInt(e.target.value))}
                  className="bg-raised border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>{i % 12 === 0 ? 12 : i % 12} {i < 12 ? 'AM' : 'PM'}</option>
                  ))}
                </select>
                <span className="text-xs text-muted">:</span>
                <select
                  id="automation-minute"
                  aria-label="Minute"
                  value={form.minute}
                  onChange={(e) => set('minute', parseInt(e.target.value))}
                  className="bg-raised border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {[0, 15, 30, 45].map((m) => (
                    <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
                  ))}
                </select>
              </div>

              {/* Day of week for weekly */}
              {form.preset === 'weekly' && (
                <div className="flex items-center gap-1.5">
                  <label htmlFor="automation-day-of-week" className="text-xs text-muted">Day</label>
                  <select
                    id="automation-day-of-week"
                    value={form.dayOfWeek}
                    onChange={(e) => set('dayOfWeek', parseInt(e.target.value))}
                    className="bg-raised border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    {DAYS_OF_WEEK.map((d, i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Day of month for monthly */}
              {form.preset === 'monthly' && (
                <div className="flex items-center gap-1.5">
                  <label htmlFor="automation-day-of-month" className="text-xs text-muted">Day of month</label>
                  <select
                    id="automation-day-of-month"
                    value={form.dayOfMonth}
                    onChange={(e) => set('dayOfMonth', parseInt(e.target.value))}
                    className="bg-raised border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    {Array.from({ length: 28 }, (_, i) => (
                      <option key={i + 1} value={i + 1}>{i + 1}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {form.preset === 'custom' && (
            <div className="flex items-center gap-3">
              <input
                id="automation-cron"
                aria-label="Cron expression"
                type="text"
                value={form.cron_expression}
                onChange={(e) => set('cron_expression', e.target.value)}
                placeholder="e.g. 0 9 * * 1"
                className="flex-1 bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm font-mono placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
              />
            </div>
          )}

          {/* Plain-English preview */}
          <p className="text-xs text-muted">{cronPreview}</p>
        </div>

        {/* Space */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-space" className="text-sm font-medium text-foreground">Space (optional)</label>
          <select
            id="automation-space"
            value={form.space_id}
            onChange={(e) => set('space_id', e.target.value)}
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          >
            <option value="">No specific space</option>
            {(spaces.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>

        {/* Model override */}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="automation-model" className="text-sm font-medium text-foreground">Model override (optional)</label>
          <input
            id="automation-model"
            type="text"
            value={form.model_override}
            onChange={(e) => set('model_override', e.target.value)}
            placeholder="e.g. claude-opus-4-5"
            className="bg-raised text-foreground border border-border rounded-md px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-colors duration-150"
          />
        </div>

        {/* Enabled toggle */}
        <div className="flex items-center justify-between py-2 border-t border-border">
          <div>
            <p className="text-sm font-medium text-foreground">Enabled</p>
            <p className="text-xs text-muted">When disabled, this automation will not run on schedule.</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-label="Toggle automation enabled"
            aria-checked={form.enabled}
            onClick={() => set('enabled', !form.enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 ${form.enabled ? 'bg-primary' : 'bg-raised border border-border'}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${form.enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </button>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="primary" onClick={handleSubmit} loading={saving}>
            {editing ? 'Save Changes' : 'Create Automation'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
  automation: Automation | null;
  onClose: () => void;
  onEdit: (a: Automation) => void;
  onDeleted: () => void;
  onTriggered: () => void;
}

function DetailPanel({ automation, onClose, onEdit, onDeleted, onTriggered }: DetailPanelProps) {
  const qc = useQueryClient();
  const [confirmRun, setConfirmRun] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runsPage, setRunsPage] = useState(1);
  const PAGE_SIZE = 10;

  const runsQuery = $api.useQuery(
    'get',
    '/api/v1/automations/{automation_id}/runs',
    { params: { path: { automation_id: automation?.id ?? '' }, query: { limit: PAGE_SIZE * runsPage } } },
    { enabled: !!automation?.id }
  );

  const handleTrigger = async () => {
    if (!automation) return;
    setTriggering(true);
    setRunError(null);
    try {
      const res = await api.POST('/api/v1/automations/{automation_id}/trigger', {
        params: { path: { automation_id: automation.id } },
      });
      if ((res as { error?: unknown }).error) throw new Error();
      setConfirmRun(false);
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/automations/{automation_id}/runs'] });
      onTriggered();
    } catch {
      setRunError('Failed to trigger automation.');
    } finally {
      setTriggering(false);
    }
  };

  const handleDelete = async () => {
    if (!automation) return;
    setDeleting(true);
    try {
      await api.DELETE('/api/v1/automations/{automation_id}', {
        params: { path: { automation_id: automation.id } },
      });
      onDeleted();
      onClose();
    } catch {
      // swallow
    } finally {
      setDeleting(false);
    }
  };

  const runs: AutomationRun[] = runsQuery.data ?? automation?.runs ?? [];

  return (
    <Panel open={!!automation} onClose={onClose} title={automation?.name ?? ''} width="480px">
      {automation && (
        <div className="space-y-5">
          {/* Description */}
          {automation.description && (
            <p className="text-sm text-muted">{automation.description}</p>
          )}

          {/* Config grid */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-0.5">Schedule</p>
              <p className="text-foreground">{describeCron(automation.cron_expression)}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-0.5">Status</p>
              <div className="flex items-center gap-2">
                {automation.enabled ? (
                  // Static green dot — enabled but idle; pulsing reserved for actively running
                  <span className="relative flex h-2.5 w-2.5 shrink-0">
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-success" />
                  </span>
                ) : (
                  <StatusDot status={undefined} />
                )}
                <span className="text-foreground">{automation.enabled ? 'Enabled' : 'Disabled'}</span>
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-0.5">Last run</p>
              <p className="text-foreground">
                {automation.last_run_at ? timeAgo(automation.last_run_at) : 'Never'}
              </p>
            </div>
            {automation.last_run_status && (
              <div>
                <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-0.5">Last status</p>
                <Badge variant={statusVariant(automation.last_run_status)}>
                  {automation.last_run_status}
                </Badge>
              </div>
            )}
          </div>

          {/* Instruction */}
          <div>
            <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-1">Instruction</p>
            <p className="text-sm text-foreground bg-raised rounded-md px-3 py-2 whitespace-pre-wrap">
              {automation.instruction}
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-2 flex-wrap">
            {!confirmRun ? (
              <Button size="sm" variant="primary" onClick={() => setConfirmRun(true)}>
                Run now
              </Button>
            ) : (
              <div className="flex items-center gap-2 flex-1">
                <span className="text-xs text-muted">Run {automation.name} immediately?</span>
                <Button size="sm" variant="primary" onClick={handleTrigger} loading={triggering}>
                  Continue
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmRun(false)}>
                  Cancel
                </Button>
              </div>
            )}
            {!confirmRun && (
              <>
                <Button size="sm" variant="secondary" onClick={() => onEdit(automation)}>
                  Edit
                </Button>
                {!confirmDelete ? (
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>
                    Delete
                  </Button>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-destructive">Click again to confirm</span>
                    <Button size="sm" variant="danger" onClick={handleDelete} loading={deleting}>
                      Delete
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                      Cancel
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>

          {runError && <p className="text-xs text-destructive">{runError}</p>}

          {/* Run history */}
          <div>
            <h4 className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Run history</h4>
            {runsQuery.isLoading && (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-10 rounded bg-raised animate-pulse" />
                ))}
              </div>
            )}
            {!runsQuery.isLoading && runs.length === 0 && (
              <p className="text-sm text-muted py-2">No runs yet.</p>
            )}
            {runs.slice(0, PAGE_SIZE * runsPage).map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
            {runs.length === PAGE_SIZE * runsPage && (
              <button
                type="button"
                onClick={() => setRunsPage((p) => p + 1)}
                className="mt-2 text-xs text-primary hover:underline"
              >
                View more runs
              </button>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ─── Automation row ───────────────────────────────────────────────────────────

interface AutomationRowProps {
  automation: Automation;
  onClick: () => void;
  onToggle: () => void;
  toggling: boolean;
}

function AutomationRow({ automation, onClick, onToggle, toggling }: AutomationRowProps) {
  return (
    <Card className="transition-colors duration-150 hover:border-primary/40">
      <CardBody className="py-3 px-4">
        <div className="flex items-center gap-3">
          {/* Status dot */}
          <StatusDot status={automation.last_run_status} />

          {/* Clickable info area */}
          <button
            type="button"
            className="flex-1 min-w-0 text-left"
            onClick={onClick}
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-foreground">{automation.name}</span>
              <Badge variant={automation.enabled ? 'success' : 'info'} className="text-[11px]">
                {automation.enabled ? 'enabled' : 'disabled'}
              </Badge>
            </div>
            <div className="flex items-center gap-3 mt-0.5 flex-wrap">
              <span className="text-xs text-muted">{describeCron(automation.cron_expression)}</span>
              {automation.last_run_at && (
                <span className="text-xs text-muted">
                  Last run {timeAgo(automation.last_run_at)}
                  {automation.last_run_status && (
                    <> &middot; <Badge variant={statusVariant(automation.last_run_status)} className="text-[10px] ml-1">
                      {automation.last_run_status}
                    </Badge></>
                  )}
                </span>
              )}
              {!automation.last_run_at && (
                <span className="text-xs text-muted">Never run</span>
              )}
            </div>
          </button>

          {/* Enable/disable toggle */}
          <button
            type="button"
            role="switch"
            aria-label={`Toggle ${automation.name}`}
            aria-checked={automation.enabled}
            onClick={(e) => { e.stopPropagation(); onToggle(); }}
            disabled={toggling}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1 disabled:opacity-50 shrink-0 ${automation.enabled ? 'bg-primary' : 'bg-raised border border-border'}`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${automation.enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
          </button>
        </div>
      </CardBody>
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Automations() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingAutomation, setEditingAutomation] = useState<Automation | null>(null);
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());

  const { data, isLoading, error: listError } = $api.useQuery('get', '/api/v1/automations');
  const automations: Automation[] = data ?? [];

  const selected = automations.find((a) => a.id === selectedId) ?? null;

  const openCreate = () => {
    setEditingAutomation(null);
    setFormOpen(true);
  };

  const openEdit = (a: Automation) => {
    setEditingAutomation(a);
    setFormOpen(true);
  };

  const handleSaved = () => {
    qc.invalidateQueries({ queryKey: ['get', '/api/v1/automations'] });
  };

  const handleToggle = async (automation: Automation) => {
    setTogglingIds((prev) => new Set([...prev, automation.id]));
    try {
      const res = await api.PATCH('/api/v1/automations/{automation_id}', {
        params: { path: { automation_id: automation.id } },
        body: { enabled: !automation.enabled },
      });
      if ((res as { error?: unknown }).error) {
        console.error('Toggle failed for automation', automation.id, (res as { error?: unknown }).error);
        return;
      }
      qc.invalidateQueries({ queryKey: ['get', '/api/v1/automations'] });
    } finally {
      setTogglingIds((prev) => { const next = new Set(prev); next.delete(automation.id); return next; });
    }
  };

  return (
    <div className="max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-foreground">Automations</h1>
          <p className="text-sm text-muted mt-0.5">Scheduled agent tasks that run automatically.</p>
        </div>
        <Button variant="primary" onClick={openCreate}>
          New Automation
        </Button>
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardBody className="py-3">
                <div className="flex items-center gap-3">
                  <div className="h-2.5 w-2.5 rounded-full bg-raised animate-pulse shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-4 w-48 rounded bg-raised animate-pulse" />
                    <div className="h-3 w-32 rounded bg-raised animate-pulse" />
                  </div>
                  <div className="h-5 w-9 rounded-full bg-raised animate-pulse shrink-0" />
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {/* Error state */}
      {!isLoading && listError && (
        <Card>
          <CardBody className="py-12 text-center">
            <p className="text-sm font-medium text-foreground mb-1">Failed to load automations</p>
            <p className="text-xs text-muted">Something went wrong. Try refreshing the page.</p>
          </CardBody>
        </Card>
      )}

      {/* Empty state */}
      {!isLoading && !listError && automations.length === 0 && (
        <Card>
          <CardBody className="py-12 text-center">
            <div className="text-4xl mb-3 select-none">&#9201;</div>
            <p className="text-sm font-medium text-foreground mb-1">No automations yet</p>
            <p className="text-xs text-muted mb-4">Create a scheduled agent task to get started.</p>
            <Button variant="primary" onClick={openCreate}>New Automation</Button>
          </CardBody>
        </Card>
      )}

      {/* Automation list */}
      {!isLoading && automations.length > 0 && (
        <div className="space-y-2">
          {automations.map((automation) => (
            <AutomationRow
              key={automation.id}
              automation={automation}
              onClick={() => setSelectedId(automation.id === selectedId ? null : automation.id)}
              onToggle={() => handleToggle(automation)}
              toggling={togglingIds.has(automation.id)}
            />
          ))}
        </div>
      )}

      {/* Detail panel */}
      <DetailPanel
        key={selectedId ?? ''}
        automation={selected}
        onClose={() => setSelectedId(null)}
        onEdit={openEdit}
        onDeleted={() => {
          setSelectedId(null);
          qc.invalidateQueries({ queryKey: ['get', '/api/v1/automations'] });
        }}
        onTriggered={() => {
          qc.invalidateQueries({ queryKey: ['get', '/api/v1/automations'] });
        }}
      />

      {/* Create/edit form */}
      <AutomationForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        editing={editingAutomation}
        onSaved={handleSaved}
      />
    </div>
  );
}
