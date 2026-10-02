/**
 * Combobox — custom accessible select replacement (no native <select>).
 *
 * Keyboard: ArrowUp/Down, Home/End, Enter/Space to choose, Escape to close,
 * typeahead by first letter. ARIA listbox pattern. Closes on outside click.
 */

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { CaretDown, Check } from "@phosphor-icons/react";

export interface ComboOption {
  value: string;
  label: string;
  hint?: string;
}

interface ComboboxProps {
  value: string;
  onChange: (value: string) => void;
  options: ComboOption[];
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
  ariaDescribedby?: string;
}

export default function Combobox({
  value,
  onChange,
  options,
  placeholder = "Chọn…",
  disabled = false,
  invalid = false,
  id,
  ariaDescribedby,
}: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const typeahead = useRef<{ str: string; at: number }>({ str: "", at: 0 });
  const autoId = useId();
  const listId = `${id ?? autoId}-list`;

  const selected = options.find((o) => o.value === value) ?? null;

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Highlight the selected option when opening.
  useEffect(() => {
    if (!open) return;
    const idx = options.findIndex((o) => o.value === value);
    setActive(idx >= 0 ? idx : 0);
  }, [open, options, value]);

  // Keep the active option scrolled into view.
  useEffect(() => {
    if (!open || active < 0) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  function choose(idx: number) {
    const opt = options[idx];
    if (!opt) return;
    onChange(opt.value);
    setOpen(false);
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;

    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActive((a) => Math.min(a + 1, options.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
        break;
      case "Home":
        e.preventDefault();
        setActive(0);
        break;
      case "End":
        e.preventDefault();
        setActive(options.length - 1);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        break;
      case "Escape":
        e.preventDefault();
        setOpen(false);
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        if (e.key.length === 1) {
          const now = Date.now();
          const ta = typeahead.current;
          ta.str = now - ta.at > 600 ? e.key : ta.str + e.key;
          ta.at = now;
          const hit = options.findIndex((o) =>
            o.label.toLowerCase().startsWith(ta.str.toLowerCase())
          );
          if (hit >= 0) setActive(hit);
        }
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        id={id}
        disabled={disabled}
        onClick={() => !disabled && setOpen((o) => !o)}
        onKeyDown={onKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-describedby={ariaDescribedby}
        className={`flex w-full items-center justify-between gap-2 rounded-xl border bg-white/[0.03] px-3.5 py-2.5 text-left text-sm text-zinc-100 transition-colors hover:bg-white/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:opacity-40 ${
          invalid ? "border-rose-500/60" : "border-white/10"
        }`}
      >
        <span className={`truncate ${selected ? "" : "text-zinc-500"}`}>
          {selected ? selected.label : placeholder}
        </span>
        <CaretDown
          size={16}
          weight="bold"
          className={`shrink-0 text-zinc-500 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          className="pop-in absolute z-20 mt-1.5 max-h-64 w-full overflow-auto rounded-xl border border-white/10 bg-zinc-900 p-1 shadow-2xl shadow-black/60"
        >
          {options.length === 0 && (
            <li className="px-3 py-2 text-sm text-zinc-500">Không có lựa chọn</li>
          )}
          {options.map((opt, idx) => {
            const isSel = opt.value === value;
            const isActive = idx === active;
            return (
              <li
                key={opt.value}
                data-idx={idx}
                role="option"
                aria-selected={isSel}
                onMouseEnter={() => setActive(idx)}
                onClick={() => choose(idx)}
                className={`flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm ${
                  isActive ? "bg-emerald-500/15 text-emerald-100" : "text-zinc-200"
                }`}
              >
                <span className="min-w-0 truncate">
                  {opt.label}
                  {opt.hint && (
                    <span className="ml-1.5 text-xs text-zinc-500">{opt.hint}</span>
                  )}
                </span>
                {isSel && (
                  <Check size={15} weight="bold" className="shrink-0 text-emerald-400" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
