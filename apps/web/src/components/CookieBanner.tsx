"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const storageKey = "anytoolai_cookie_notice_v1";

export function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => {
      setVisible(window.localStorage.getItem(storageKey) !== "accepted");
    }, 0);

    return () => window.clearTimeout(id);
  }, []);

  if (!visible) {
    return null;
  }

  return (
    <aside className="cookie-banner" aria-label="Уведомление о cookies">
      <span className="badge badge-running">Cookies</span>
      <p>
        Сайт использует функциональные cookies для работы интерфейса и сохранения
        выбранных настроек. Подробнее описано в политике cookies.
      </p>
      <div className="cookie-actions">
        <button
          className="btn-primary"
          type="button"
          onClick={() => {
            window.localStorage.setItem(storageKey, "accepted");
            setVisible(false);
          }}
        >
          Принять
        </button>
        <Link className="btn-secondary" href="/ru/cookies">
          Настроить
        </Link>
      </div>
    </aside>
  );
}
