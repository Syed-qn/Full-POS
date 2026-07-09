import { Link } from "react-router-dom";
import { EmptyState } from "./EmptyState";
import { Button } from "./Button";
import s from "./NoAccessScreen.module.css";

export function NoAccessScreen({
  title = "No access",
  description = "Your role does not include this module. Switch to a manager account or ask an owner to update your staff role.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className={s.wrap} data-testid="no-access-screen">
      <EmptyState
        title={title}
        description={description}
        action={
          <Link to="/" className={s.linkReset}>
            <Button type="button" variant="primary" size="lg">
              Back to Live Ops
            </Button>
          </Link>
        }
      />
    </div>
  );
}
