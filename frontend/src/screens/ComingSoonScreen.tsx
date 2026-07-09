import { Link } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";

export function ComingSoonScreen({
  title,
  description,
  phaseHint = "Scheduled in the UI/UX redesign phases plan.",
}: {
  title: string;
  description: string;
  phaseHint?: string;
}) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState
        title={`${title} — coming soon`}
        description={`${description} ${phaseHint}`}
        action={
          <Link to="/">
            <Button variant="primary" size="lg">
              Back to Live Ops
            </Button>
          </Link>
        }
      />
      <BottomActionBar>
        <Link to="/new-order">
          <Button size="touch">New Order</Button>
        </Link>
        <Link to="/orders">
          <Button variant="ghost" size="lg">
            Orders
          </Button>
        </Link>
      </BottomActionBar>
    </>
  );
}
