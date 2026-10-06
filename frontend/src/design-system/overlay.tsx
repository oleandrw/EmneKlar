/*
 * Modal dialog and drawer built on the native <dialog> element: focus is
 * contained and the background is inert (browser-provided), Esc closes, and
 * focus returns to the element that opened the dialog.
 */
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";

import { Button, IconButton, cx } from "./primitives";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  variant?: "modal" | "drawer";
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** When false, Esc and the close button are disabled (e.g. while a write is running). */
  dismissible?: boolean;
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  variant = "modal",
  initialFocusRef,
  dismissible = true,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  const descId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal();
      window.setTimeout(() => {
        if (initialFocusRef?.current) initialFocusRef.current.focus();
      }, 0);
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, initialFocusRef]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const handleClose = () => {
      const target = opener.current;
      if (target instanceof HTMLElement && target.isConnected) target.focus();
    };
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  return (
    <dialog
      ref={ref}
      className={cx("ek-dialog", size !== "md" && `ek-dialog--${size}`, variant === "drawer" && "ek-dialog--drawer")}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (dismissible) onCloseRef.current();
      }}
    >
      {open ? (
        <>
          <div className="ek-dialog__header">
            <div>
              <h2 id={titleId} className="ek-dialog__title">
                {title}
              </h2>
              {description ? (
                <p id={descId} className="ek-dialog__description">
                  {description}
                </p>
              ) : null}
            </div>
            <IconButton label="Lukk" size="sm" onClick={onClose} disabled={!dismissible}>
              <X aria-hidden="true" />
            </IconButton>
          </div>
          <div className="ek-dialog__body">{children}</div>
          {footer ? <div className="ek-dialog__footer">{footer}</div> : null}
        </>
      ) : null}
    </dialog>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel,
  cancelLabel = "Avbryt",
  danger,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: ReactNode;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      initialFocusRef={cancelRef}
      dismissible={!loading}
      footer={
        <>
          <Button ref={cancelRef} onClick={onClose} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="ek-stack ek-small">{children}</div>
    </Dialog>
  );
}
