import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNotifications } from '../context/NotificationContext';
import { deploymentService } from '../api/deploymentService';
import { accessService } from '../api/accessService';
import { awsIssueService } from '../api/issueService';
import Card from '../components/ui/Card';
import { StatusBadge, RecordIdBadge } from '../components/ui/Badge';
import { SkeletonCard, SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';

/* =========================================================
   QUICK CREATE (+) MENU
   Each option sends the user to that module's page and asks
   it to auto-open its own "New …" modal via ?new=1.
   The Issue Tracker has been removed from the app.
   `show` decides who sees each option (matches what the
   backend actually allows, so nobody gets a dead link).
   ========================================================= */
const QUICK_CREATE_OPTIONS = [
  {
    label: 'New Deployment',
    icon: '🚀',
    to: '/deployments?new=1',
    // Only Developers / QA raise deployment requests.
    show: ({ user }) => user?.role === 'Developer' || user?.role === 'QA'
  },
  {
    label: 'New Access Request',
    icon: '🔐',
    to: '/access?new=1',
    show: () => true
  },
  {
    label: 'New AWS Issue',
    icon: '☁️',
    to: '/aws-issues?new=1',
    // AWS Issues are DevOps-only.
    show: ({ user }) => user?.role === 'DevOps'
  },
  {
    label: 'New Application',
    icon: '🧩',
    to: '/applications?new=1',
    // Admin power only.
    show: ({ isAdmin }) => isAdmin,
    divider: true
  }
];

function QuickCreateMenu({ user, isAdmin }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const wrapRef = useRef(null);

  const options = QUICK_CREATE_OPTIONS.filter((opt) =>
    opt.show({ user, isAdmin })
  );

  useEffect(() => {
    function onClickOutside(e) {
      if (
        wrapRef.current &&
        !wrapRef.current.contains(e.target)
      ) {
        setOpen(false);
      }
    }

    document.addEventListener('mousedown', onClickOutside);
    return () =>
      document.removeEventListener('mousedown', onClickOutside);
  }, []);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen(o => !o)}
        className="
          inline-flex
          items-center
          gap-1.5
          bg-brand-500
          hover:bg-brand-600
          text-white
          text-sm
          font-medium
          px-3.5
          py-2
          rounded-lg
          shadow-sm
          transition-colors
        "
      >
        <span className="text-base leading-none">+</span>
        New
      </button>

      {open && (
        <div
          className="
            absolute
            right-0
            mt-2
            w-56
            bg-white
            border
            border-ink-200/70
            rounded-xl2
            shadow-raised
            py-1.5
            z-20
          "
        >
          {options.map(opt => (
            <div key={opt.label}>
            {opt.divider && (
              <div className="my-1.5 border-t border-ink-100" />
            )}
            <button
              onClick={() => {
                setOpen(false);
                navigate(opt.to);
              }}
              className="
                w-full
                text-left
                px-3.5
                py-2
                text-sm
                text-ink-700
                hover:bg-ink-50
                flex
                items-center
                gap-2.5
              "
            >
              <span className="text-base leading-none">
                {opt.icon}
              </span>
              {opt.label}
            </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TYPE_ROUTE = {
  DEPLOYMENT: 'deployments',
  ACCESS: 'access',
  AWS_ISSUE: 'aws-issues'
};

const TYPE_LABEL = {
  DEPLOYMENT: 'Deployment',
  ACCESS: 'Access',
  AWS_ISSUE: 'AWS Issue'
};

function greeting() {
  const h = new Date().getHours();

  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';

  return 'Good evening';
}

/* =========================================================
   SCROLLABLE DASHBOARD BOX
   Fixed height (not max-height) so all four boxes are the
   exact same size no matter how little/how much content is
   inside them. overflow-y-scroll keeps a visible scroll
   line on the right edge at all times.
   ========================================================= */
function ScrollableCard({
  children,
  className = '',
  height = 'h-[260px]'
}) {
  const scrollRef = useRef(null);

  return (
    <div className="relative">
      <div
        ref={scrollRef}
        className={`
          ${height}
          overflow-y-scroll
          overflow-x-hidden
          pr-1
          ${className}
        `}
        style={{
          scrollbarWidth: 'thin'
        }}
      >
        {children}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user, isAdmin } = useAuth();
  const navigate = useNavigate();

  // AWS Issues are DevOps-only (see QUICK_CREATE_OPTIONS above and
  // the DevOps-only fetch below), so only the DevOps dashboard shows that
  // box. Everyone else (Developer, QA, Admin-without-DevOps-role) gets the
  // Access Requests box stretched to fill the full row instead.
  const showAwsIssues = user?.role === 'DevOps';

  // Developer / QA: the server only sends them the requests they raised, so every box on
  // this dashboard is "my" data. They see ALL their own requests (not just the pending ones).
  const isRequester = user?.role === 'Developer' || user?.role === 'QA';

  const [state, setState] = useState({
    loading: true,
    error: null,
    deployments: [],
    access: [],
    prod: []
  });

  async function load() {
    setState(s => ({
      ...s,
      loading: true,
      error: null
    }));

    try {
      const [
        deployments,
        access,
        prod
      ] = await Promise.all([
        deploymentService.list(),
        accessService.list(),
        // AWS issues are DevOps-only; skip the call for others.
        user?.role === 'DevOps'
          ? awsIssueService.list()
          : Promise.resolve([])
      ]);

      setState({
        loading: false,
        error: null,
        deployments,
        access,
        prod
      });
    } catch (e) {
      setState(s => ({
        ...s,
        loading: false,
        error: e.message
      }));
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Live refresh: when a new notification arrives (e.g. a new deployment
  // request), reload the dashboard boxes so the counts stay current.
  const { unreadCount } = useNotifications();
  const prevUnread = useRef(unreadCount);
  useEffect(() => {
    if (unreadCount > prevUnread.current) load();
    prevUnread.current = unreadCount;
  }, [unreadCount]);

  const stats = useMemo(() => {
    const {
      deployments,
      access
    } = state;

    return {
      pendingDeployments:
        deployments.filter(
          d => d.Status === 'REQUESTED'
        ).length,

      pendingAccess:
        access.filter(
          a => a.Status === 'REQUESTED'
        ).length,

      inProgress:
        [...deployments, ...access].filter(
          r => r.Status === 'IN_PROGRESS'
        ).length,

      failedDeployments:
        deployments.filter(
          d => d.Status === 'COMPLETED_FAILED'
        ).length,

      successfulDeployments:
        deployments.filter(
          d => d.Status === 'COMPLETED_SUCCESS'
        ).length
    };
  }, [state]);

  /* =========================================================
     DEPLOYMENT REQUESTS
     ========================================================= */
  const deploymentRequests = useMemo(() => {
    return state.deployments
      .filter(
        d => isRequester || d.Status === 'REQUESTED'
      )
      .sort(
        (a, b) =>
          new Date(b.CreatedAt) -
          new Date(a.CreatedAt)
      )
      .slice(0, isRequester ? 30 : 6);
  }, [state]);

  /* =========================================================
     ACCESS REQUESTS
     ========================================================= */
  const accessRequests = useMemo(() => {
    return state.access
      .filter(
        a => isRequester || a.Status === 'REQUESTED'
      )
      .sort(
        (a, b) =>
          new Date(b.CreatedAt) -
          new Date(a.CreatedAt)
      )
      .slice(0, isRequester ? 30 : 6);
  }, [state]);

  /* =========================================================
     AWS ISSUES
     ========================================================= */
  const awsIssues = useMemo(() => {
    return state.prod
      .filter(
        p => p.Status === 'OPEN'
      )
      .sort(
        (a, b) =>
          new Date(b.CreatedAt) -
          new Date(a.CreatedAt)
      )
      .slice(0, 6);
  }, [state]);

  const recentActivity = useMemo(() => {
    const all = [
      ...state.deployments,
      ...state.access,
      ...state.prod
    ];

    return all
      .sort(
        (a, b) =>
          new Date(
            b.UpdatedAt || b.CreatedAt
          ) -
          new Date(
            a.UpdatedAt || a.CreatedAt
          )
      )
      .slice(0, 8);
  }, [state]);

  if (state.error) {
    return (
      <ErrorState
        message={state.error}
        onRetry={load}
      />
    );
  }

  const cards = [
    {
      label: 'Successful Deployments',
      value: stats.successfulDeployments,
      tone: 'success',
      to: '/deployments?status=COMPLETED_SUCCESS'
    },
    {
      label: 'Pending Deployments',
      value: stats.pendingDeployments,
      tone: 'warning',
      to: '/deployments?status=REQUESTED'
    },
    {
      label: 'Failed Deployments',
      value: stats.failedDeployments,
      tone: 'danger',
      to: '/deployments?status=COMPLETED_FAILED'
    },
    {
      label: 'Pending Access',
      value: stats.pendingAccess,
      tone: 'warning',
      to: '/access?status=REQUESTED'
    },
    {
      label: 'In Progress',
      value: stats.inProgress,
      tone: 'info',
      to: '/deployments?status=IN_PROGRESS'
    }
  ];

  return (
    <div className="space-y-5 animate-fade-in">

      {/* =================================================
          PAGE HEADER
         ================================================= */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-ink-900">
            {greeting()}, {user?.name?.split(' ')[0]} 👋
          </h1>

          <p className="text-sm text-ink-400 mt-1">
            {isRequester
              ? 'Here are the requests you have raised and where they stand.'
              : "Here's what needs your attention right now."}
          </p>
        </div>

        <QuickCreateMenu user={user} isAdmin={isAdmin} />
      </div>

      {/* =================================================
          OPERATIONS OVERVIEW
         ================================================= */}
      <section>
        <h2 className="text-sm font-semibold text-ink-700 mb-2">
          Operations Overview
        </h2>

        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">

          {state.loading
            ? Array.from({ length: 5 }).map(
                (_, i) => (
                  <SkeletonCard key={i} />
                )
              )
            : cards.map(c => (
                <button
                  key={c.label}
                  onClick={() =>
                    navigate(c.to)
                  }
                  className="text-left"
                >
                  <Card className="p-3 hover:shadow-raised transition-shadow cursor-pointer">
                    <p className="text-xs font-medium text-ink-400">
                      {c.label}
                    </p>

                    <p
                      className={`
                        text-2xl
                        font-bold
                        mt-1
                        ${
                          c.tone === 'danger'
                            ? 'text-danger'
                            : c.tone === 'warning'
                            ? 'text-warning'
                            : c.tone === 'info'
                            ? 'text-info'
                            : c.tone === 'success'
                            ? 'text-success'
                            : 'text-ink-900'
                        }
                      `}
                    >
                      {c.value}
                    </p>
                  </Card>
                </button>
              ))}
        </div>
      </section>

      {/* =================================================
          DASHBOARD LIST BOXES
          Developer / QA: two boxes side by side (My Deployment Requests + My Access Requests).
          DevOps / Admin: 2 up, 2 down — all four boxes the same size.
         ================================================= */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

        {/* =================================================
            DEPLOYMENT REQUESTS
           ================================================= */}
        <section>
          <h2 className="text-sm font-semibold text-ink-700 mb-2">
            {isRequester ? 'My Deployment Requests' : 'Deployment Requests'}
          </h2>

          <Card className="overflow-hidden">
            <ScrollableCard height={isRequester ? 'h-[320px]' : 'h-[190px]'}>
              <div className="divide-y divide-ink-100">

                {state.loading &&
                  Array.from({ length: 3 }).map(
                    (_, i) => (
                      <SkeletonRow key={i} />
                    )
                  )}

                {!state.loading &&
                  deploymentRequests.length === 0 && (
                    <EmptyState
                      icon="✅"
                      title={isRequester ? 'You have not raised any deployment requests' : 'No deployment requests'}
                    />
                  )}

                {!state.loading &&
                  deploymentRequests.map(d => (
                    <button
                      key={d['Record ID']}
                      onClick={() =>
                        navigate(
                          `/deployments/${d['Record ID']}`
                        )
                      }
                      className="
                        w-full
                        text-left
                        px-4
                        py-3
                        flex
                        items-center
                        gap-3
                        hover:bg-ink-50
                      "
                    >
                      <RecordIdBadge
                        id={d['Record ID']}
                      />

                      <span className="text-sm text-ink-900 flex-1 truncate">
                        {d.Project ||
                          d.Application ||
                          d.Service ||
                          'Deployment Request'}
                      </span>

                      <StatusBadge
                        status={d.Status}
                      />
                    </button>
                  ))}
              </div>
            </ScrollableCard>
          </Card>
        </section>

        {!isRequester && (
          <>
        {/* =================================================
            RECENT ACTIVITY
           ================================================= */}
        <section>
          <h2 className="text-sm font-semibold text-ink-700 mb-2">
            Recent Activity
          </h2>

          <Card className="overflow-hidden">
            <ScrollableCard height="h-[190px]">
              <div className="divide-y divide-ink-100">

                {state.loading &&
                  Array.from({ length: 3 }).map(
                    (_, i) => (
                      <SkeletonRow key={i} />
                    )
                  )}

                {!state.loading &&
                  recentActivity.length === 0 && (
                    <EmptyState
                      title="No activity yet"
                    />
                  )}

                {!state.loading &&
                  recentActivity.map(r => (
                    <button
                      key={r['Record ID']}
                      onClick={() =>
                        navigate(
                          `/${TYPE_ROUTE[r['Record Type']]}/${r['Record ID']}`
                        )
                      }
                      className="
                        w-full
                        text-left
                        px-4
                        py-3
                        flex
                        items-center
                        gap-3
                        hover:bg-ink-50
                      "
                    >
                      <RecordIdBadge
                        id={r['Record ID']}
                      />

                      <span className="text-xs text-ink-400 w-28 shrink-0">
                        {TYPE_LABEL[
                          r['Record Type']
                        ]}
                      </span>

                      <span className="text-sm text-ink-900 flex-1 truncate">
                        {r.Project ||
                          r.ErrorMessage}
                      </span>

                      <StatusBadge
                        status={r.Status}
                      />
                    </button>
                  ))}
              </div>
            </ScrollableCard>
          </Card>
        </section>
          </>
        )}

        {/* =================================================
            ACCESS REQUESTS
            Spans the full row (and shows more rows) on
            dashboards that don't also show AWS Issues.
           ================================================= */}
        <section className={showAwsIssues || isRequester ? '' : 'sm:col-span-2'}>
          <h2 className="text-sm font-semibold text-ink-700 mb-2">
            {isRequester ? 'My Access Requests' : 'Access Requests'}
          </h2>

          <Card className="overflow-hidden">
            <ScrollableCard height={isRequester ? 'h-[320px]' : showAwsIssues ? 'h-[190px]' : 'h-[260px]'}>
              <div className="divide-y divide-ink-100">

                {state.loading &&
                  Array.from({ length: 3 }).map(
                    (_, i) => (
                      <SkeletonRow key={i} />
                    )
                  )}

                {!state.loading &&
                  accessRequests.length === 0 && (
                    <EmptyState
                      icon="🔐"
                      title={isRequester ? 'You have not raised any access requests' : 'No access requests'}
                    />
                  )}

                {!state.loading &&
                  accessRequests.map(a => (
                    <button
                      key={a['Record ID']}
                      onClick={() =>
                        navigate(
                          `/access/${a['Record ID']}`
                        )
                      }
                      className="
                        w-full
                        text-left
                        px-4
                        py-3
                        flex
                        items-center
                        gap-3
                        hover:bg-ink-50
                      "
                    >
                      <RecordIdBadge
                        id={a['Record ID']}
                      />

                      <span className="text-sm text-ink-900 flex-1 truncate">
                        {a.Project ||
                          a.Application ||
                          a.System ||
                          'Access Request'}
                      </span>

                      <StatusBadge
                        status={a.Status}
                      />
                    </button>
                  ))}
              </div>
            </ScrollableCard>
          </Card>
        </section>

        {/* =================================================
            AWS ISSUES
            DevOps-only box — hidden entirely everywhere else
            (Access Requests takes the freed-up space instead).
           ================================================= */}
        {showAwsIssues && (
          <section>
            <h2 className="text-sm font-semibold text-ink-700 mb-2">
              AWS Issues
            </h2>

            <Card className="overflow-hidden">
              <ScrollableCard height="h-[190px]">
                <div className="divide-y divide-ink-100">

                  {state.loading &&
                    Array.from({ length: 3 }).map(
                      (_, i) => (
                        <SkeletonRow key={i} />
                      )
                    )}

                  {!state.loading &&
                    awsIssues.length === 0 && (
                      <EmptyState
                        icon="☁️"
                        title="No AWS issues"
                      />
                    )}

                  {!state.loading &&
                    awsIssues.map(p => (
                      <button
                        key={p['Record ID']}
                        onClick={() =>
                          navigate(
                            `/aws-issues/${p['Record ID']}`
                          )
                        }
                        className="
                          w-full
                          text-left
                          px-4
                          py-3
                          flex
                          items-center
                          gap-3
                          hover:bg-ink-50
                        "
                      >
                        <RecordIdBadge
                          id={p['Record ID']}
                        />

                        <span className="text-sm text-ink-900 flex-1 truncate">
                          {p.Project ||
                            p.Application ||
                            p.ErrorMessage ||
                            'AWS Issue'}
                        </span>

                        <StatusBadge
                          status={p.Status}
                        />
                      </button>
                    ))}
                </div>
              </ScrollableCard>
            </Card>
          </section>
        )}

      </div>
    </div>
  );
}