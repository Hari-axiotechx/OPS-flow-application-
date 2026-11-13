import { useState } from 'react';
import Modal from './Modal';
import Button from './Button';
import EmailNotifyFooter from './EmailRecipients';

export default function ConfirmDialog({ open, onClose, onConfirm, title, description, requireReason, maxReasonLength, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger, email }) {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [mailError, setMailError] = useState('');

  async function handleConfirm() {
    if (requireReason && !reason.trim()) return;
    const problem = email ? email.validate() : '';
    if (problem) { setMailError(problem); return; }
    setMailError('');
    setLoading(true);
    try {
      await onConfirm(reason, email ? email.options() : undefined);
      setReason('');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      width={email ? 'max-w-xl' : 'max-w-md'}
      maxHeight="max-h-[70vh]"
      footer={(() => {
        const buttons = (
          <>
            <Button variant="secondary" onClick={onClose}>{cancelLabel}</Button>
            <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={handleConfirm} disabled={requireReason && !reason.trim()}>
              {confirmLabel}
            </Button>
          </>
        );
        return email ? (
          <EmailNotifyFooter email={email} open={open}>{buttons}</EmailNotifyFooter>
        ) : buttons;
      })()}
    >
      {description && <p className="text-sm text-ink-600 mb-3">{description}</p>}
      {requireReason && (
        <div>
          <label className="block text-xs font-medium text-ink-600 mb-1.5">Reason <span className="text-danger">*</span></label>
          <textarea
            className="w-full border border-ink-200 rounded-lg px-3 py-2 text-sm focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none"
            rows={3}
            maxLength={maxReasonLength}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Explain why…"
          />
          {maxReasonLength && (
            <p className="mt-1 text-right text-xs text-ink-400">
              {reason.length} / {maxReasonLength}
            </p>
          )}
        </div>
      )}
      {mailError && <p className="text-xs text-danger mt-3">{mailError}</p>}
    </Modal>
  );
}
