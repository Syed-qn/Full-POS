/** Paging for the card lists on Inventory.
 *
 * A card list that silently stops at five reads as "that is all there is",
 * which is how a count from three days ago becomes invisible. This shows the
 * RANGE rather than "page 2 of 4": when a movement is missing, what you need
 * to know is how far down the list you have already read.
 */
import { useState } from "react";
import s from "../screens/InventoryScreen.module.css";
import p from "./ListPager.module.css";

export const PAGE_SIZE = 5;

export type Paged<T> = {
  rows: T[];
  page: number;
  pageCount: number;
  first: number;
  last: number;
  total: number;
  setPage: (n: number) => void;
};

/**
 * Slice a list into pages.
 *
 * The page index is CLAMPED on read rather than reset by an effect: these
 * lists grow and shrink under the reader — a live event refetches, answering
 * a transfer moves a row from one list to another — and an out-of-range page
 * would render an empty card with no control left to click back with.
 */
export function usePaged<T>(items: T[], size: number = PAGE_SIZE): Paged<T> {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(items.length / size));
  const safe = Math.min(page, pageCount - 1);
  const first = safe * size + 1;
  const rows = items.slice(first - 1, first - 1 + size);
  return {
    rows,
    page: safe,
    pageCount,
    first,
    last: first + rows.length - 1,
    total: items.length,
    setPage,
  };
}

/** Nothing at all when everything fits — controls for a three-row list are
 *  furniture that teaches people to stop reading the bottom of cards. */
export function ListPager<T>({ paged, label }: { paged: Paged<T>; label: string }) {
  if (paged.pageCount <= 1) return null;
  return (
    <div className={p.pager}>
      <button
        type="button"
        className={`${s.rowBtn} ${p.pageBtn}`}
        disabled={paged.page === 0}
        aria-label={`Previous page of ${label}`}
        onClick={() => paged.setPage(paged.page - 1)}
      >
        Back
      </button>
      <span className={p.pageCount}>
        {paged.first}–{paged.last} of {paged.total}
      </span>
      <button
        type="button"
        className={`${s.rowBtn} ${p.pageBtn}`}
        disabled={paged.page >= paged.pageCount - 1}
        aria-label={`Next page of ${label}`}
        onClick={() => paged.setPage(paged.page + 1)}
      >
        Next
      </button>
    </div>
  );
}
