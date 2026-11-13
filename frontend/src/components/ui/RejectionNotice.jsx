export default function RejectionNotice({ reason }) {
  if (!reason) return null;

  return (
    <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3" role="alert">
      <p className="text-xs font-bold uppercase tracking-wide text-red-700">
        Rejection reason
      </p>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm font-medium text-red-900">
        {reason}
      </p>
    </div>
  );
}
