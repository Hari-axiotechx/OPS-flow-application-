import { useEffect, useRef, useState } from 'react';
import BackArrow from '../components/ui/BackArrow';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { applicationService } from '../api/applicationService';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { DatePicker } from '../components/ui/FormBits';
import { SkeletonRow } from '../components/ui/Skeleton';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import { useVoiceForm } from '../voice/useVoiceForm';
import { voiceForms } from '../voice/voiceForms';

function todayLocal() {
  const d = new Date();
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}

function formatDate(value) {
  if (!value) return '—';

  const d = new Date(`${value}T00:00:00`);

  if (Number.isNaN(d.getTime())) return value;

  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

export default function Applications() {
  const { isAdmin, setConfig } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();

  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [name, setName] = useState('');
  const [date, setDate] = useState(todayLocal());
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const formRef = useRef(null);
  const nameRef = useRef(null);

  // Voice assistant ("Hello Ops, add an application") types the name into the box below.
  // It can never press Submit: the user does.
  useVoiceForm('APPLICATION', {
    open: true,
    form: { name },
    reset: () => {
      setName('');
      setFormError('');
    },
    close: () => {},
    apply: (patch) => {
      if (patch.name !== undefined) setName(String(patch.name).slice(0, 100));
    },
  });

  async function load() {
    setLoading(true);
    setError(null);

    try {
      setApps(await applicationService.list());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (params.get('new') === '1' && !loading) {
      formRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });

      setTimeout(() => nameRef.current?.focus(), 300);

      const next = new URLSearchParams(params);
      next.delete('new');

      setParams(next, { replace: true });
    }
  }, [params, loading, setParams]);

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError('');

    const trimmed = name.trim();

    if (!trimmed) {
      setFormError('Application name is required.');
      nameRef.current?.focus();
      return;
    }

    if (!date) {
      setFormError('Date is required.');
      return;
    }

    if (
      apps.some(
        (a) => a.name.toLowerCase() === trimmed.toLowerCase()
      )
    ) {
      setFormError(`"${trimmed}" already exists.`);
      return;
    }

    setSaving(true);

    try {
      const res = await applicationService.add(trimmed, date);

      if (res?.config) {
        setConfig(res.config);
      }

      toast.success(
        `${trimmed} added. It's now available for deployments.`
      );
      voiceForms.submitted('APPLICATION', trimmed);

      setName('');
      setDate(todayLocal());

      await load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    const app = deleteTarget;
    setDeleting(app.name);

    try {
      const res = await applicationService.remove(app.name);

      if (res?.config) {
        setConfig(res.config);
      }

      toast.success(`${app.name} deleted successfully.`);
      setDeleteTarget(null);

      await load();
    } catch (err) {
      toast.error(err.message || 'Failed to delete application.');
    } finally {
      setDeleting(null);
    }
  }

  if (!isAdmin) return null;

  return (
    <div className="space-y-5 animate-fade-in">

      {/* Page Header */}
      <div>
        <h1 className="text-xl font-bold text-ink-900 flex items-center gap-3">
          <BackArrow />Applications
        </h1>

        <p className="text-sm text-ink-400 mt-0.5">
          Applications available in deployment, access and AWS issue requests.
        </p>
      </div>

      {/* Current Applications */}
      <Card className="overflow-hidden">

        <div className="px-4 py-3 border-b border-ink-100 flex items-center justify-between">
          <p className="text-sm font-semibold text-ink-700">
            All applications
          </p>

          {!loading && !error && (
            <span className="text-xs text-ink-400">
              {apps.length} total
            </span>
          )}
        </div>

        {error ? (
          <ErrorState
            message={error}
            onRetry={load}
          />
        ) : (
          <div className="overflow-x-auto">

            <table className="w-full text-sm">

              <thead>
                <tr className="text-left text-xs text-ink-400 bg-ink-50">

                  <th className="px-4 py-2.5 font-medium w-12">
                    #
                  </th>

                  <th className="px-4 py-2.5 font-medium">
                    Application name
                  </th>

                  <th className="px-4 py-2.5 font-medium">
                    Date
                  </th>

                  <th className="px-4 py-2.5 font-medium">
                    Added by
                  </th>

                  <th className="px-4 py-2.5 font-medium text-right">
                    Action
                  </th>

                </tr>
              </thead>

              <tbody className="divide-y divide-ink-100">

                {/* Loading */}
                {loading &&
                  Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      <td colSpan={5}>
                        <SkeletonRow />
                      </td>
                    </tr>
                  ))
                }

                {/* Empty */}
                {!loading && apps.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <EmptyState
                        icon="🧩"
                        title="No applications yet"
                      />
                    </td>
                  </tr>
                )}

                {/* Applications */}
                {!loading &&
                  apps.map((a, i) => (
                    <tr
                      key={a.name}
                      className="hover:bg-ink-50"
                    >

                      <td className="px-4 py-3 text-ink-400">
                        {i + 1}
                      </td>

                      <td className="px-4 py-3 font-medium text-ink-900">
                        {a.name}
                      </td>

                      <td className="px-4 py-3 text-ink-600">
                        {formatDate(a.date)}
                      </td>

                      <td className="px-4 py-3 text-ink-600">
                        {a.createdBy === 'system' ? (
                          <span className="text-xs text-ink-400">
                            Default
                          </span>
                        ) : (
                          a.createdBy
                        )}
                      </td>

                      <td className="px-4 py-3 text-right">

                        {a.createdBy === 'system' ? (
                          <span className="text-xs text-ink-400">
                            Default
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(a)}
                            disabled={deleting === a.name}
                            className="
                              inline-flex items-center
                              rounded-lg
                              border border-red-200
                              bg-red-50
                              px-3 py-1.5
                              text-xs font-medium
                              text-red-600
                              hover:bg-red-100
                              disabled:opacity-50
                              disabled:cursor-not-allowed
                            "
                          >
                            {deleting === a.name
                              ? 'Deleting...'
                              : 'Delete'}
                          </button>
                        )}

                      </td>

                    </tr>
                  ))
                }

              </tbody>

            </table>

          </div>
        )}

      </Card>

      {/* Add New Application */}
      <div ref={formRef}>

        <Card className="p-5">

          <h2 className="text-sm font-semibold text-ink-900">
            Add new application
          </h2>

          <p className="text-xs text-ink-400 mt-0.5">
            Only admins can add applications. Everyone will see it in their dropdowns right away.
          </p>

          <form
            onSubmit={handleSubmit}
            className="mt-4 grid grid-cols-1 sm:grid-cols-[1fr_200px_auto] gap-3 items-end"
          >

            {/* Application Name */}
            <label className="block">

              <span className="block text-xs font-medium text-ink-600 mb-1.5">
                Application name{' '}
                <span className="text-danger">*</span>
              </span>

              <input
                ref={nameRef}
                type="text"
                value={name}
                maxLength={100}
                onChange={(e) => {
                  setName(e.target.value);
                  setFormError('');
                }}
                placeholder="e.g. Stylo-Partner"
                className="
                  w-full h-10 rounded-lg
                  border border-ink-200
                  bg-white px-3
                  text-sm text-ink-900
                  placeholder:text-ink-300
                  focus:outline-none
                  focus:ring-2
                  focus:ring-brand-100
                  focus:border-brand-400
                "
              />

            </label>

            {/* Date */}
            <label className="block">

              <span className="block text-xs font-medium text-ink-600 mb-1.5">
                Date <span className="text-danger">*</span>
              </span>

              <DatePicker
                value={date}
                onChange={(value) => {
                  setDate(value);
                  setFormError('');
                }}
              />

            </label>

            {/* Submit */}
            <Button
              type="submit"
              loading={saving}
              className="h-10 px-6"
            >
              Submit
            </Button>

          </form>

          {formError && (
            <p
              className="mt-3 text-sm text-danger"
              role="alert"
            >
              {formError}
            </p>
          )}

        </Card>

      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Delete application?"
        description={`Are you sure you want to delete "${deleteTarget?.name}"? It will no longer be available in Deployment, Access Request, and AWS Issue dropdowns.`}
        confirmLabel="Delete"
        danger
      />

    </div>
  );
}