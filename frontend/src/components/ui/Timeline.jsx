const ACTION_TONE = {
  CREATED: 'brand', APPROVED: 'success', REJECTED: 'danger', STATUS_CHANGE: 'info',
  REASSIGNED: 'warning', ASSIGNED: 'warning', UPDATED: 'info', DETAILS_EDITED: 'info', DELETED: 'danger',
  REOPENED: 'warning', ROLE_CHANGE: 'brand', ACTIVATED: 'success', DEACTIVATED: 'neutral'
};

const DOT_COLOR = {
  brand: 'bg-brand-500', success: 'bg-success', danger: 'bg-danger',
  info: 'bg-info', warning: 'bg-warning', neutral: 'bg-neutral'
};

/* Resolves a "USR-000002"-style id to "USR-000002 (Jane Doe)" when a
   matching user is found in the users list; falls back to the bare id
   otherwise (e.g. user list still loading, or record has been removed). */
function userLabel(id, usersById) {
  if (!id) return id;
  const name = usersById?.[id];
  return name ? `${id} (${name})` : id;
}

function actionLabel(entry, usersById) {
  switch (entry.action) {
    case 'CREATED': return 'Created';
    case 'STATUS_CHANGE': return `Status changed to ${humanStatus(entry.newValue)}`;
    case 'APPROVED': return `Approved · role set to ${entry.newValue}`;
    case 'REJECTED': return 'Rejected';
    case 'ASSIGNED': return `Assigned to ${userLabel(entry.newValue, usersById)}`;
    case 'REASSIGNED': return `Reassigned to ${userLabel(entry.newValue, usersById)}`;
    case 'UPDATED': return 'Details updated';
    case 'DETAILS_EDITED': return `Edited ${humanFieldName(entry.reason)}`;
    case 'DELETED': return 'Deleted';
    case 'REOPENED': return 'Reopened';
    case 'ROLE_CHANGE': return 'Role / permissions changed';
    case 'ACTIVATED': return 'Account activated';
    case 'DEACTIVATED': return 'Account deactivated';
    default: return entry.action;
  }
}

const FIELD_LABELS = {
  dbChange: 'DB / schema change flag',
  dbChangeDetails: 'DB / schema change details',
  dbChangeFileName: 'DB / schema change file name',
  dbChangeFileData: 'DB / schema change file',
  envVarChange: 'environment variable change flag',
  envVarDetails: 'environment variable details',
  thirdPartyApiChange: 'third-party API change flag',
  thirdPartyApiDetails: 'third-party API details',
  additionalInfo: 'additional info',
};

function humanFieldName(key) {
  return FIELD_LABELS[key] || key || 'details';
}

function humanStatus(s) {
  if (!s) return '';
  return s.replaceAll('_', ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase());
}

export default function Timeline({ entries = [], users = [] }) {
  // Map of "USR-000002" -> "Jane Doe", built once per render so
  // actionLabel() can turn a bare id into "id (name)".
  const usersById = {};
  users.forEach((u) => {
    if (u?.id) usersById[u.id] = u.name;
  });

  if (entries.length === 0) {
    return <div className="text-sm text-ink-400 py-6 text-center">No history yet.</div>;
  }
  return (
    <ol className="relative pl-1">
      {entries.map((e, i) => {
        const tone = ACTION_TONE[e.action] || 'neutral';
        const isLast = i === entries.length - 1;
        return (
          <li key={i} className="relative pl-7 pb-6 last:pb-0">
            {!isLast && <span className="absolute left-[7px] top-3 bottom-0 w-px bg-ink-200" />}
            <span className={`absolute left-0 top-1 h-4 w-4 rounded-full ring-4 ring-white ${DOT_COLOR[tone]}`} />
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm font-medium text-ink-900">{actionLabel(e, usersById)}</p>
              <time className="font-mono text-[11px] text-ink-400 shrink-0">
                {e.at ? new Date(e.at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
              </time>
            </div>
            <p className="text-xs text-ink-400 mt-0.5">by {e.performedBy || 'system'}</p>
            {e.reason && e.action !== 'DETAILS_EDITED' && <p className="text-xs text-ink-600 mt-1.5 bg-ink-50 rounded-lg px-2.5 py-1.5">"{e.reason}"</p>}
          </li>
        );
      })}
    </ol>
  );
}