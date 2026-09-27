import { JobStatus } from "./JobStatus.tsx";

export default async function Analysis({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return (
    <div className="stack">
      <h1>Your analysis</h1>
      <JobStatus runId={runId} />
    </div>
  );
}
