import { NextResponse } from "next/server";

/**
 * Frontend liveness probe - consumed by the Docker HEALTHCHECK and any
 * future orchestrator (Kubernetes, ECS, ...).
 */
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    status: "healthy",
    service: "cybershield-frontend",
    timestamp: new Date().toISOString(),
  });
}
