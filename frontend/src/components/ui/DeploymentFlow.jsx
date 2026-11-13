/**
 * Deployment progress — green flow, no names / dates / other details.
 *
 *   (✓) Requested ──── (✓) Approved ──── (✓) In Progress ──── (✓) Success
 *
 * - Steps that are reached turn GREEN with a tick.   Steps not reached yet stay grey.
 * - The end result (Success / Failed / Rolled back) is NOT shown while the deployment is
 *   still running. It appears only after DevOps clicks it, and only that one is shown.
 * - Rejected: Requested ──── Rejected.
 *
 * File location: frontend/src/components/ui/DeploymentFlow.jsx  (replace the whole file)
 */
const GREEN = '#16A34A';
const RED = '#DC2626';
const ORANGE = '#D97706';
const GREY = '#C9CED6';

const STEPS = [
  { key: 'REQUESTED', label: 'Requested' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'IN_PROGRESS', label: 'In Progress' },
];

const RESULTS = {
  COMPLETED_SUCCESS: { label: 'Success', color: GREEN, icon: 'tick' },
  COMPLETED_FAILED: { label: 'Failed', color: RED, icon: 'cross' },
  ROLLED_BACK: { label: 'Rolled back', color: ORANGE, icon: 'undo' },
  REJECTED: { label: 'Rejected', color: RED, icon: 'cross' },
};

function Icon({ type }) {
  const common = {
    width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: '#fff',
    strokeWidth: 3, strokeLinecap: 'round', strokeLinejoin: 'round',
  };
  if (type === 'cross') {
    return (<svg {...common}><path d="M6 6l12 12" /><path d="M18 6L6 18" /></svg>);
  }
  if (type === 'undo') {
    return (<svg {...common}><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /></svg>);
  }
  return (<svg {...common}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>);
}

function Node({ label, color, icon, state }) {
  // state: 'done' | 'current' | 'todo'
  const on = state !== 'todo';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div
        style={{
          width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: on ? color : '#fff',
          border: `2px ${on ? 'solid' : 'dashed'} ${on ? color : GREY}`,
          boxShadow: state === 'current' ? `0 0 0 4px ${color}2E` : 'none',
          transition: 'all .2s',
        }}
      >
        {on && <Icon type={icon} />}
      </div>
      <span style={{ fontSize: 14, fontWeight: 700, whiteSpace: 'nowrap', color: on ? color : '#9AA1AE' }}>
        {label}
      </span>
    </div>
  );
}

function Line({ on, color = GREEN }) {
  return (
    <div
      style={{
        width: 44, height: 3, borderRadius: 2, flexShrink: 0,
        background: on ? color : '#E3E6EB',
      }}
    />
  );
}

export default function DeploymentFlow({ status, rejectionReason }) {
  const result = RESULTS[status];                 // only set once the deployment has ended / been rejected
  const rejected = status === 'REJECTED';
  const finished = !!result && !rejected;
  // 0 = Requested, 1 = Approved, 2 = In Progress
  const rank = finished ? 2 : Math.max(0, STEPS.findIndex((s) => s.key === status));

  return (
    <div className="rounded-xl border border-ink-100 bg-white px-4 py-3.5 shadow-sm">
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
        {/* Requested is always reached — the request exists */}
        <Node label="Requested" color={GREEN} icon="tick" state={rank === 0 && !rejected && !finished ? 'current' : 'done'} />

        {rejected ? (
          <>
            <Line on color={RED} />
            <Node label={result.label} color={result.color} icon={result.icon} state="current" />
          </>
        ) : (
          <>
            <Line on={rank >= 1} />
            <Node label="Approved" color={GREEN} icon="tick" state={rank > 1 || finished ? 'done' : rank === 1 ? 'current' : 'todo'} />
            <Line on={rank >= 2} />
            <Node label="In Progress" color={GREEN} icon="tick" state={finished ? 'done' : rank === 2 ? 'current' : 'todo'} />

            {/* Success / Failed / Rolled back stay hidden until one of them is clicked */}
            {finished && (
              <>
                <Line on color={result.color} />
                <Node label={result.label} color={result.color} icon={result.icon} state="current" />
              </>
            )}
          </>
        )}
      </div>
      {rejected && <div className="mt-4"><RejectionNotice reason={rejectionReason} /></div>}
    </div>
  );
}
import RejectionNotice from './RejectionNotice';
