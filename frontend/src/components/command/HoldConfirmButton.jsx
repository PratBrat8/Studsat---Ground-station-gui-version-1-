import React, { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Press-and-hold confirm (PRD A.5.1 / Phase 11).
 * A click (down+up) never fires — only a completed hold does.
 */
export default function HoldConfirmButton({
  holdMs = 2000,
  disabled = false,
  onConfirm,
  className = 'btn',
  children,
  ariaLabel,
}) {
  const [progress, setProgress] = useState(0);
  const [holding, setHolding] = useState(false);
  const startRef = useRef(0);
  const rafRef = useRef(0);
  const firedRef = useRef(false);
  const onConfirmRef = useRef(onConfirm);
  onConfirmRef.current = onConfirm;

  const cancel = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    startRef.current = 0;
    firedRef.current = false;
    setHolding(false);
    setProgress(0);
  }, []);

  useEffect(() => {
    if (!holding || disabled) {
      if (disabled) cancel();
      return undefined;
    }
    const tick = (now) => {
      const elapsed = now - startRef.current;
      const p = Math.min(1, elapsed / holdMs);
      setProgress(p);
      if (p >= 1 && !firedRef.current) {
        firedRef.current = true;
        setHolding(false);
        setProgress(0);
        rafRef.current = 0;
        Promise.resolve(onConfirmRef.current?.()).catch(() => {});
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [holding, disabled, holdMs, cancel]);

  const begin = (event) => {
    if (disabled) return;
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    firedRef.current = false;
    startRef.current = performance.now();
    setProgress(0);
    setHolding(true);
  };

  const onKeyDown = (event) => {
    if (disabled) return;
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    if (event.repeat || holding) return;
    firedRef.current = false;
    startRef.current = performance.now();
    setProgress(0);
    setHolding(true);
  };

  const onKeyUp = (event) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      cancel();
    }
  };

  return (
    <button
      type="button"
      className={`hold-confirm ${className} ${holding ? 'holding' : ''}`}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={holding}
      onPointerDown={begin}
      onPointerUp={cancel}
      onPointerCancel={cancel}
      onPointerLeave={cancel}
      onLostPointerCapture={cancel}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onClick={(e) => e.preventDefault()}
      onContextMenu={(e) => e.preventDefault()}
    >
      <span
        className="hold-confirm-fill"
        style={{ transform: `scaleX(${progress})` }}
        aria-hidden="true"
      />
      <span className="hold-confirm-label">{children}</span>
    </button>
  );
}
