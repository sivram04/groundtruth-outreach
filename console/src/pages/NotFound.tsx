import { Card } from "../components";

export function NotFound({ what = "There is no such page." }: { what?: string }) {
  return (
    <>
      <h1>Not found</h1>
      <Card>
        <p>{what}</p>
        <p>
          <a href="#/">Back to the dashboard</a>
        </p>
      </Card>
    </>
  );
}
