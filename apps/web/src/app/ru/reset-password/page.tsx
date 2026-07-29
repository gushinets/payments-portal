import { Suspense } from "react";
import { PasswordResetConfirmClient } from "@/features/password-reset";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <PasswordResetConfirmClient />
    </Suspense>
  );
}

function ResetPasswordFallback() {
  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">Загрузка формы смены пароля...</div>
    </section>
  );
}
