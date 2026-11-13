import { useEffect, useRef } from 'react';
import { voiceForms } from './voiceForms';

/**
 * Lets the voice assistant drive a form.
 *
 *   useVoiceForm('DEPLOYMENT', {
 *     open,                                   // register only while the form is visible
 *     form,                                   // the form's current state
 *     apply: (patch) => setForm(...),         // write values coming from the assistant
 *     reset: () => setForm(emptyForm()),      // start from a clean form
 *     close: onClose,                         // "cancel" by voice
 *   });
 */
export function useVoiceForm(kind, { open, form, apply, reset, close }) {
  const formRef = useRef(form);
  formRef.current = form;
  const fns = useRef({});
  fns.current = { apply, reset, close };

  useEffect(() => {
    if (!open) return undefined;
    return voiceForms.register(kind, {
      getForm: () => formRef.current,
      apply: (patch) => fns.current.apply?.(patch),
      reset: () => fns.current.reset?.(),
      close: () => fns.current.close?.(),
    });
  }, [open, kind]);
}
